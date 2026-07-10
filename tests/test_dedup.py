from app.dedup import compute_superseded


def test_three_same_name_records_newest_wins():
    records = [
        {"id": "old", "name": "TownInspector", "created_at": "2026-07-10T01:00:00.000Z"},
        {"id": "mid", "name": "TownInspector", "created_at": "2026-07-10T02:00:00.000Z"},
        {"id": "new", "name": "towninspector", "created_at": "2026-07-10T03:00:00.000Z"},
    ]
    mapping = compute_superseded(records)
    assert mapping["new"] is None
    assert mapping["old"] == "new"
    assert mapping["mid"] == "new"


def test_distinct_names_all_active():
    records = [
        {"id": "a", "name": "Foo", "created_at": "2026-07-10T01:00:00.000Z"},
        {"id": "b", "name": "Bar", "created_at": "2026-07-10T01:00:00.000Z"},
    ]
    mapping = compute_superseded(records)
    assert mapping == {"a": None, "b": None}


def test_missing_created_at_does_not_crash_and_loses_tiebreak():
    records = [
        {"id": "a", "name": "Foo", "created_at": None},
        {"id": "b", "name": "Foo", "created_at": "2026-07-10T01:00:00.000Z"},
    ]
    mapping = compute_superseded(records)
    assert mapping["b"] is None
    assert mapping["a"] == "b"
