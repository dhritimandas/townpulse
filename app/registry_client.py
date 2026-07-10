"""Fetch the Nanda Town registry with defensive parsing and a last-good cache.

Registry API-shape drift (spec §11 risk) must never take the prober down --
any fetch or parse failure falls back to the last successfully-fetched
snapshot, cached to a file next to the SQLite DB so it survives restarts.
"""

import json
import logging
from pathlib import Path

import httpx

from app.config import REGISTRY_URL, USER_AGENT

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("id", "name", "source_type", "created_at")


def _cache_path_for(db_path: str) -> Path:
    db = Path(db_path)
    return db.with_name(db.stem + ".registry_cache.json")


def _read_cache(db_path: str) -> list[dict]:
    path = _cache_path_for(db_path)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _write_cache(db_path: str, records: list[dict]) -> None:
    path = _cache_path_for(db_path)
    try:
        path.write_text(json.dumps(records))
    except OSError:
        logger.warning("failed to write registry cache to %s", path)


def _extract_records(payload: object) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("skills"), list):
        return payload["skills"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"unrecognized registry payload shape: {type(payload).__name__}")


def _is_valid_record(record: object) -> bool:
    return isinstance(record, dict) and all(field in record for field in REQUIRED_FIELDS)


async def fetch_registry(db_path: str) -> list[dict]:
    """Fetch and defensively parse the registry.

    On any network/parse failure, or if zero valid records survive
    filtering, falls back to the last-good cache (possibly empty on a cold
    start with no prior successful fetch).
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(REGISTRY_URL)
            resp.raise_for_status()
            payload = resp.json()
        records = _extract_records(payload)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("registry fetch failed (%s); falling back to last-good cache", exc)
        return _read_cache(db_path)

    valid = [r for r in records if _is_valid_record(r)]
    skipped = len(records) - len(valid)
    if skipped:
        logger.warning("skipped %d malformed registry records", skipped)

    if valid:
        _write_cache(db_path, valid)
        return valid

    logger.warning("registry returned zero valid records; falling back to last-good cache")
    return _read_cache(db_path)
