"""
Carregador de configurações YAML.
Lê os arquivos da pasta /configs e faz cache em memória.
Suporta reload em runtime para não precisar reiniciar o servidor.
"""
import os
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Diretório de configs: pode ser sobrescrito via variável de ambiente
_CONFIGS_DIR = Path(os.environ.get("AI_CONFIGS_DIR", str(Path(__file__).parent.parent.parent.parent.parent / "configs")))

_cache: dict[str, Any] = {}
def _configs_dir() -> Path:
    return _CONFIGS_DIR


def load_yaml(filename: str, force_reload: bool = False) -> dict:
    """
    Carrega um arquivo YAML da pasta configs/.
    Faz cache em memória. Use force_reload=True para reler o arquivo.
    """
    if not force_reload and filename in _cache:
        return _cache[filename]

    path = _configs_dir() / filename
    if not path.exists():
        logger.warning(f"Config file not found: {path}. Using empty dict.")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _cache[filename] = data
        logger.info(f"Loaded config: {path}")
        return data
    except Exception as e:
        logger.error(f"Error loading config {path}: {e}")
        return {}


def reload_all():
    """Força reload de todos os configs em cache."""
    _cache.clear()
    logger.info("Config cache cleared — next access will reload from disk")


def get_decision_tree() -> dict:
    return load_yaml("decision_tree.yaml")


def get_llm_providers() -> dict:
    return load_yaml("llm_providers.yaml")


def get_tutor_prompts() -> dict:
    return load_yaml("tutor_prompts.yaml")
