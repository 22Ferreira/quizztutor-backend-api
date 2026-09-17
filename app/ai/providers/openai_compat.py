"""
Provedor genérico compatível com OpenAI.
Funciona com: Groq, OpenRouter, Ollama, OpenAI, Together, etc.
Usa httpx.AsyncClient global (singleton) para reutilizar conexões.
"""
import logging
import os
import re
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from app.ai.providers.base import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)

# Alguns modelos "raciocinadores" (ex: gpt-oss da Groq, DeepSeek-R1 e
# variantes via OpenRouter) escrevem o próprio pensamento interno dentro
# do texto da resposta, em tags <think>...</think> — isso pode incluir a
# resposta certa da questão dita sem rodeio nenhum, em inglês, fora do
# personagem do tutor. O parâmetro certo (reasoning_format) evita isso
# na origem pra quem suporta, mas isso aqui é uma rede de segurança pra
# qualquer provedor/modelo que vaze raciocínio desse jeito mesmo assim —
# ex: o roteador automático da OpenRouter (openrouter/free) pode cair
# num modelo raciocinador sem a gente escolher isso.
_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_UNCLOSED_THINK_RE = re.compile(r"<think>.*", re.IGNORECASE | re.DOTALL)


def _strip_reasoning(content: str) -> str:
    cleaned = _THINK_TAG_RE.sub("", content)
    cleaned = _UNCLOSED_THINK_RE.sub("", cleaned)  # <think> sem fechar (resposta cortada no meio)
    return cleaned.strip()


# Visto ao vivo: o roteador automático da OpenRouter (openrouter/free)
# pode escolher, por engano, um modelo de MODERAÇÃO (tipo Llama Guard)
# em vez de um modelo de conversa — esses modelos só existem pra
# classificar "seguro/inseguro", nunca respondem de verdade. A saída
# deles é sempre nesse formato fixo, então dá pra reconhecer com
# segurança e tratar como falha do provedor (não como resposta real).
_SAFETY_CLASSIFIER_RE = re.compile(
    r"^\s*(user safety|response safety)\s*:\s*(safe|unsafe)\b", re.IGNORECASE
)


def _looks_like_safety_classifier_output(content: str) -> bool:
    return bool(_SAFETY_CLASSIFIER_RE.match(content))


def _is_retryable(exc: BaseException) -> bool:
    # Mesma lógica do provedor Gemini (app/ai/providers/gemini.py): só
    # vale a pena tentar de novo em falha passageira (rede, erro 5xx).
    # Retentar um 429 (cota/limite estourado) é inútil — o provedor vai
    # continuar recusando pelo mesmo motivo, e só atrasa a resposta.
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)

# Client global compartilhado: reutiliza pool de conexões TCP
_GLOBAL_CLIENT: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _GLOBAL_CLIENT
    if _GLOBAL_CLIENT is None or _GLOBAL_CLIENT.is_closed:
        _GLOBAL_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _GLOBAL_CLIENT


class OpenAICompatProvider(BaseLLMProvider):
    def _resolve_api_key(self) -> str | None:
        env_var = self.config.get("api_key_env")
        if not env_var:
            return None
        return os.environ.get(env_var, "")

    def _resolve_base_url(self) -> str:
        url_env = self.config.get("base_url_env")
        if url_env:
            # os.environ.get só usa o default se a variável não existir — se
            # ela existir só vazia (ex: "OLLAMA_BASE_URL=" no .env), isso
            # retornava "" e gerava uma URL relativa inválida.
            return os.environ.get(url_env) or self.config.get("base_url_default", "http://localhost:11434")
        return self.config.get("base_url", "")

    def _get_model(self) -> str:
        models = self.config.get("models", {})
        return models.get("default", "gpt-3.5-turbo")

    # Isolado numa função própria que RAISA o erro (em vez de devolver um
    # LLMResponse), porque é assim que o @retry consegue interceptar —
    # antes, o @retry ficava em cima de chat(), que sempre capturava a
    # exceção e devolvia um resultado, então o retry nunca disparava,
    # nem pra falha passageira de rede que valeria a pena tentar de novo.
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _post(self, url: str, payload: dict, headers: dict, timeout: float) -> dict:
        client = get_http_client()
        r = await client.post(url, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        base_url = self._resolve_base_url()
        api_key = self._resolve_api_key()
        model = self._get_model()
        params = self._get_params(**kwargs)
        timeout = self.config.get("timeout_seconds", 30)

        # Algumas base_url já vêm com "/v1" no final (Groq, OpenRouter),
        # outras não (Ollama) — sem essa checagem, as que já tinham
        # viravam ".../v1/v1/chat/completions" e davam 404.
        base = base_url.rstrip('/')
        url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.update(self.config.get("headers_extra", {}))

        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": params.get("temperature", 0.3),
            "max_tokens": params.get("max_tokens", 1024),
        }
        payload.update(self.config.get("extra_payload", {}))

        try:
            data = await self._post(url, payload, headers, timeout)
            content = _strip_reasoning(data["choices"][0]["message"]["content"] or "")
            if not content:
                logger.warning(f"[{self.name}] Resposta vazia (sem erro HTTP) — modelo: {model}")
                return LLMResponse(content="", provider=self.name, model=model, success=False, error="Resposta vazia do provedor")
            if _looks_like_safety_classifier_output(content):
                # O roteador automático escolheu um modelo de moderação
                # por engano — nunca é uma resposta de verdade pro
                # aluno, sempre tratar como se o provedor tivesse
                # falhado, pra cair no próximo da cadeia de fallback.
                logger.warning(f"[{self.name}] Modelo devolveu saída de classificador de segurança, não uma resposta — modelo: {model} | conteudo={content[:200]!r}")
                return LLMResponse(content="", provider=self.name, model=model, success=False, error="Modelo escolhido era um classificador de moderação, não um modelo de conversa")
            return LLMResponse(content=content, provider=self.name, model=model, success=True)
        except httpx.HTTPStatusError as e:
            logger.warning(f"[{self.name}] HTTP error: {e.response.status_code} — {e.response.text[:200]}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=str(e))
        except Exception as e:
            logger.warning(f"[{self.name}] Error: {e}")
            return LLMResponse(content="", provider=self.name, model=model, success=False, error=str(e))
