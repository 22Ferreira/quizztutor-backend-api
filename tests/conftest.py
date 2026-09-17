"""Configuração compartilhada de testes.

Garante que os módulos de configuração (app.ai.configs.loader) apontem
pro configs/ real do repo mesmo rodando fora do Docker — precisa ser
definido ANTES de qualquer "import app..." em qualquer teste, porque
o loader resolve o caminho uma vez só, no import do módulo.
"""
import os
from pathlib import Path

os.environ.setdefault("AI_CONFIGS_DIR", str(Path(__file__).parent.parent / "configs"))
