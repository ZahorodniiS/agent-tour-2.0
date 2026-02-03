from __future__ import annotations
from typing import Dict, Any
from collections import defaultdict

_STATE: Dict[int, Dict[str, Any]] = defaultdict(dict)

def get(chat_id: int) -> Dict[str, Any]:
    return _STATE[chat_id]

def set(chat_id: int, **kwargs):
    _STATE[chat_id].update(kwargs)

def clear(chat_id: int):
    _STATE.pop(chat_id, None)
