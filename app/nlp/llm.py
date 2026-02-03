from __future__ import annotations
import json
from typing import Dict, Any
from openai import OpenAI
from app.config import OPENAI_API_KEY, ENABLE_LLM, OPENAI_MODEL

_CLIENT = None
def _client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(api_key=OPENAI_API_KEY or None)
    return _CLIENT

SYSTEM_PROMPT = """Ти — екстрактор параметрів для пошуку турів.
Відповідай ТІЛЬКИ валідним JSON без коментарів.
Схема:
{
  "country_name": string|null,
  "from_city_name": string|null,
  "country_id": int|null,
  "from_city_id": int|null,
  "adults": int|null,
  "children": int|null,
  "child_ages": "7:4:3"|null,
  "date_from": "dd.mm.yy"|null,
  "date_till": "dd.mm.yy"|null,
  "currency_hint": "usd"|"eur"|"uah"|null,
  "budget_from": int|null,
  "budget_to": int|null
}
Правила:
- Мапити назви країн/міст через надані мапи (country_map, from_city_map). Якщо немає збігу — поверни *name, але id = null.
- Валюта: usd/дол/$ → "usd"; eur/євро/€ → "eur"; інакше "uah" або null.
- Бюджет: підтримуй "до 2000", "від 500 до 1500", "близько 1000".
- Дати: приймай dd.mm або dd.mm.yy → нормалізуй у dd.mm.yy, якщо можливо; інакше null.
- Дорослі/діти: “на 2”, “для двох дорослих і 1 дитини 7 років”.
- Якщо не впевнений — поверни null (не вигадуй).
"""

def llm_extract(user_text: str, country_map: Dict[str,int], from_city_map: Dict[str,int]) -> Dict[str, Any]:
    if not ENABLE_LLM or not OPENAI_API_KEY:
        return {}
    cl = _client()
    tool_context = {"country_map": country_map, "from_city_map": from_city_map}
    messages = [
        {"role":"system","content": SYSTEM_PROMPT},
        {"role":"user","content": f"TEXT:\n{user_text}\n\nMAPS:\n{json.dumps(tool_context, ensure_ascii=False)}"}
    ]
    try:
        resp = cl.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0,
            response_format={"type":"json_object"}
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        for k in ("country_id","from_city_id","adults","children","budget_from","budget_to"):
            if k in data and data[k] is not None:
                try:
                    data[k] = int(data[k])
                except Exception:
                    data[k] = None
        return data
    except Exception:
        return {}
