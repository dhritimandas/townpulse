"""Deduplication of registry records resubmitted under the same name.

The registry's official "edit" path is resubmission (no edit button), so the
same skill accumulates multiple rows over time. We keep every row (for
audit) but mark all but the newest per normalized name as superseded.
"""

from datetime import datetime, timezone

from app.parsing import normalize_name

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_created_at(value: str | None) -> datetime:
    if not value:
        return _EPOCH
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _EPOCH


def compute_superseded(records: list[dict]) -> dict[str, str | None]:
    """Group records by normalized name; the newest ``created_at`` per group
    is active (maps to ``None``), every other record in the group maps to
    the active record's id. Ties break by id for determinism.

    Example::

        mapping = compute_superseded([
            {"id": "old", "name": "Foo", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "new", "name": "foo", "created_at": "2026-01-02T00:00:00Z"},
        ])
        assert mapping == {"old": "new", "new": None}
    """
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(normalize_name(record.get("name")), []).append(record)

    result: dict[str, str | None] = {}
    for group in groups.values():
        active = max(group, key=lambda r: (_parse_created_at(r.get("created_at")), r["id"]))
        for record in group:
            result[record["id"]] = None if record["id"] == active["id"] else active["id"]
    return result
