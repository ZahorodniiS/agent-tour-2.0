from __future__ import annotations
from typing import Dict, Any, Optional
from collections import defaultdict

_STATE: Dict[int, Dict[str, Any]] = defaultdict(dict)

def get(chat_id: int) -> Dict[str, Any]:
    return _STATE[chat_id]

def set(chat_id: int, **kwargs):
    _STATE[chat_id].update(kwargs)

def clear(chat_id: int):
    _STATE.pop(chat_id, None)

def reset(chat_id: int, *, keep: Optional[list[str]] = None) -> Dict[str, Any]:
    """
    Скидає state для чату. Можна зберегти певні ключі (наприклад from_city_id).
    """
    keep = keep or []
    prev = _STATE.get(chat_id, {}) or {}
    new_state: Dict[str, Any] = {}
    for k in keep:
        if k in prev:
            new_state[k] = prev[k]
    _STATE[chat_id] = new_state
    return new_state
