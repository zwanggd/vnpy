from __future__ import annotations
import re
from .config import EVENT_STOPWORDS


def normalize_event(event: str | None, fallback: str) -> str:
    """Normalize event text to a stable event_key.

    1. Empty/None → f"raw:{fallback}"
    2. Lowercase + strip
    3. Remove whitespace
    4. Remove Chinese/English punctuation
    5. Remove stopwords
    6. Empty after cleaning → f"raw:{fallback}"
    """
    if not event or not event.strip():
        return f"raw:{fallback}"
    s = event.strip().casefold()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[]，。、""''：:；;,.!?！？（）()【】[{}<>《》_/\\-|]", "", s)
    for w in EVENT_STOPWORDS:
        s = s.replace(w.casefold(), "")
    if not s:
        return f"raw:{fallback}"
    return s


def generate_event_key(event: str | None, raw_news_id: int) -> str:
    return normalize_event(event, str(raw_news_id))
