"""
Módulo de Armazenamento Persistente de Atividades Concluídas.
Armazena chaves de atividades concluídas em arquivo JSON para evitar novo envio nos resumos diários.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Set, Dict, Any, List

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
COMPLETED_FILE = DATA_DIR / "completed_activities.json"


def get_activity_key(titulo: str, disciplina: str, data_vencimento: str) -> str:
    """Gera uma chave única e normalizada para a atividade."""
    norm_title = (titulo or "").strip().lower()
    norm_disc = (disciplina or "").strip().lower()
    norm_date = (data_vencimento or "").strip()
    return f"{norm_title}_{norm_disc}_{norm_date}"


def load_completed_keys() -> Set[str]:
    """Carrega o conjunto de chaves de atividades marcadas como concluídas."""
    if not COMPLETED_FILE.exists():
        return set()

    try:
        with open(COMPLETED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {item.get("key") for item in data if isinstance(item, dict) and item.get("key")}
            elif isinstance(data, dict):
                return set(data.keys())
    except Exception as e:
        logger.error("Erro ao ler %s: %s", COMPLETED_FILE, str(e))

    return set()


def mark_activity_as_done(titulo: str, disciplina: str, data_vencimento: str) -> str:
    """
    Marca uma atividade como concluída e persiste no arquivo JSON.
    Retorna a chave da atividade.
    """
    key = get_activity_key(titulo, disciplina, data_vencimento)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    items: List[Dict[str, Any]] = []
    if COMPLETED_FILE.exists():
        try:
            with open(COMPLETED_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, list):
                    items = raw
        except Exception:
            items = []

    # Verificar se já existe
    existing_keys = {item.get("key") for item in items if isinstance(item, dict)}
    if key not in existing_keys:
        items.append({
            "key": key,
            "titulo": titulo,
            "disciplina": disciplina,
            "data_vencimento": data_vencimento,
            "data_conclusao": datetime.now().isoformat()
        })
        try:
            with open(COMPLETED_FILE, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
            logger.info("Atividade '%s' registrada como concluída no arquivo %s.", titulo, COMPLETED_FILE)
        except Exception as e:
            logger.error("Erro ao salvar atividade concluída em %s: %s", COMPLETED_FILE, str(e))

    return key
