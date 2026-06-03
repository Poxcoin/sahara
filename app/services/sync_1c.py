"""
Синхронізація залишків і цін з 1С 8.3.

Підтримує два режими:
  1. Файловий: читає JSON/CSV із папки sync/
  2. Пряме підключення: викликається з BSL-обробки 1С через /api/1c/sync

Формат JSON-файлу:
    [
        {"article": "6SAK80003UW", "stock": 5, "price": 1299.00},
        ...
    ]

Або CSV (роздільник ";"):
    Артикул;Залишок;Ціна
    6SAK80003UW;5;1299
"""
import json
import csv
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SYNC_DIR = Path(__file__).parent.parent.parent / "sync"
STATE_FILE = SYNC_DIR / ".last_sync.json"

_FIELD_MAP = {
    "article":  ["article", "Артикул", "артикул", "CODE", "Код"],
    "stock":    ["stock",   "Залишок", "залишок", "КількістьЗалишок", "Quantity"],
    "price":    ["price",   "Ціна",    "ціна",    "Price"],
    "gender":   ["gender",  "Стать",   "стать"],
}


def _get(row: dict, field: str, default=None):
    for key in _FIELD_MAP.get(field, [field]):
        if key in row:
            return row[key]
    return default


def _parse_num(val, as_int=False):
    if val is None or val == "":
        return None
    try:
        s = str(val).replace(" ", "").replace(",", ".").replace("\xa0", "")
        return int(float(s)) if as_int else float(s)
    except (ValueError, TypeError):
        return None


def read_csv_export(path: Path) -> list[dict]:
    products = []
    with open(path, encoding="utf-8-sig") as f:
        sample = f.read(1024)
        f.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            article = str(_get(row, "article") or "").strip()
            if not article:
                continue
            products.append({
                "article": article,
                "stock":   _parse_num(_get(row, "stock", 0), as_int=True) or 0,
                "price":   _parse_num(_get(row, "price")),
                "gender":  str(_get(row, "gender") or "").strip() or None,
            })
    return products


def read_json_export(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("products", [])
    result = []
    for row in rows:
        article = str(_get(row, "article") or "").strip()
        if not article:
            continue
        result.append({
            "article": article,
            "stock":   _parse_num(_get(row, "stock", 0), as_int=True) or 0,
            "price":   _parse_num(_get(row, "price")),
            "gender":  str(_get(row, "gender") or "").strip() or None,
        })
    return result


def load_newest_export() -> tuple[list[dict], Path | None]:
    SYNC_DIR.mkdir(exist_ok=True)
    candidates = []
    for pattern in ("*.json", "*.csv"):
        candidates.extend(SYNC_DIR.glob(pattern))
    candidates = [f for f in candidates if not f.name.startswith(".")]
    if not candidates:
        return [], None
    newest = max(candidates, key=lambda f: f.stat().st_mtime)
    if newest.suffix == ".json":
        return read_json_export(newest), newest
    return read_csv_export(newest), newest


def save_state(file_path: Path | None, total: int, updated: int, created: int, error: str = ""):
    SYNC_DIR.mkdir(exist_ok=True)
    state = {
        "last_sync": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "file": file_path.name if file_path else None,
        "total": total,
        "updated": updated,
        "created": created,
        "error": error,
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return state


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}
