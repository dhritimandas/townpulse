"""Environment-driven configuration for Town Pulse."""

import os

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./pulse.db")
REGISTRY_URL = os.environ.get(
    "REGISTRY_URL", "https://nandatown.projectnanda.org/api/skills"
)
USER_AGENT = "TownPulse/1.0 (NandaHack participant; +https://REPLACE-WITH-LIVE-URL/about)"

PROBE_TIMEOUT_SECONDS = 10.0
PROBE_CONCURRENCY = 8
PROBE_HOST_SPACING_SECONDS = 20.0
CYCLE_INTERVAL_MINUTES = 5
