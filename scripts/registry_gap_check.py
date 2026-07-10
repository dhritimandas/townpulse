"""Fetch the Nanda Town registry, snapshot it, and scan for competing skills.

One-shot gap-verification script (RUNBOOK.md, Friday 09:00). Saves the raw JSON,
prints the total count, lists skills matching monitoring-related keywords, and
dumps one record's full field structure.
"""

import json
import urllib.request
from pathlib import Path

REGISTRY_URL = "https://nandatown.projectnanda.org/api/skills"
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "registry_snapshot_2026-07-10.json"
KEYWORDS = [
    "uptime", "health", "monitor", "monitoring", "liveness", "alive", "probe",
    "ping", "reliability", "watchdog", "status", "observability",
]


def extract_skills(payload: object) -> list[dict]:
    """Return the list of skill records regardless of top-level envelope shape."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("skills", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError(f"Unrecognized registry payload shape: {type(payload).__name__}")


def main() -> None:
    req = urllib.request.Request(
        REGISTRY_URL,
        headers={"User-Agent": "TownPulse/0.1 (NandaHack participant; gap check)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    SNAPSHOT_PATH.write_bytes(raw)
    print(f"Snapshot saved: {SNAPSHOT_PATH} ({len(raw)} bytes)")

    payload = json.loads(raw)
    skills = extract_skills(payload)
    print(f"Total skills: {len(skills)}")

    print("\n--- Keyword matches (name or description) ---")
    hits = 0
    for s in skills:
        text = f"{s.get('name', '')} {s.get('description', '')}".lower()
        matched = sorted({k for k in KEYWORDS if k in text})
        if matched:
            hits += 1
            print(f"* {s.get('name')!r} [{', '.join(matched)}]")
            print(f"  {str(s.get('description', ''))[:200]}")
    if hits == 0:
        print("(none)")

    print("\n--- Full field structure of one record ---")
    print(json.dumps(skills[0], indent=2, default=str))
    if isinstance(payload, dict):
        print(f"\nTop-level envelope keys: {sorted(payload.keys())}")


if __name__ == "__main__":
    main()
