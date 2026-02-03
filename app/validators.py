from __future__ import annotations
from typing import Dict, Any, Tuple, Optional
from datetime import datetime, timedelta

REQUIRED_FIELDS = ("country","from_city","hotel_rating","adult_amount","night_from","night_till","date_from","date_till")

def clamp_date_range(date_from: datetime, date_till: datetime, max_days: int = 12) -> Tuple[datetime, datetime, bool]:
    changed = False
    if (date_till - date_from).days > max_days:
        date_till = date_from + timedelta(days=max_days)
        changed = True
    return date_from, date_till, changed

def validate_required(params: Dict[str, Any]) -> Optional[str]:
    for f in REQUIRED_FIELDS:
        if f not in params or params[f] in (None, "", 0):
            return f
    return None

def normalize_dates(df: str, dt: str) -> Tuple[str,str]:
    return df, dt
