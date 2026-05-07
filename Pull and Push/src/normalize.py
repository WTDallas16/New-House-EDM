from __future__ import annotations

import re
import unicodedata
from typing import Any


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value)).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"\b(feat|ft|featuring|with|x)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"\b(original mix|extended mix|radio edit|edit|club mix)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]

