from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from datetime import date, datetime, timedelta


def load_master_ranker(data_root: Path):
    ranker_path = data_root / "Master_Ranking" / "src" / "ranker.py"
    if not ranker_path.exists():
        raise RuntimeError(f"Could not find master ranker at {ranker_path}")
    spec = importlib.util.spec_from_file_location("new_house_master_ranker", ranker_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load master ranker from {ranker_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def rank_inputs(data_root: Path, inputs: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranker = load_master_ranker(data_root)
    records = ranker.load_records(inputs)
    ranked = ranker.rank_records(records)
    unique = ranker.unique_records(ranked)
    return ranked, unique


def filter_records_by_lookback(
    records: list[dict[str, Any]],
    lookback_days: int,
    today: date | None = None,
) -> list[dict[str, Any]]:
    if lookback_days <= 0:
        return records
    current_day = today or date.today()
    cutoff = current_day - timedelta(days=lookback_days)
    filtered: list[dict[str, Any]] = []
    for record in records:
        article_date = parse_record_date(record.get("article_date"))
        if article_date and cutoff <= article_date <= current_day:
            filtered.append(record)
    return filtered


def parse_record_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def write_json(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
