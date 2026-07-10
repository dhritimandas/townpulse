# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Town Pulse: a reliability index for the Nanda Town skill registry
(nandatown.projectnanda.org), built for NandaHack (deadline Sat Jul 11, 2026, IST).
It continuously probes every registered skill, accumulates uptime/latency history in
SQLite, and serves a read-only JSON API — most importantly `/recommend?need=<text>`,
which returns the most reliable live skills for a stated need, with evidence.

**Read `TOWN_PULSE_SPEC.md` before writing any code — it is the authoritative spec**
(architecture §2, probe policy §3, scoring §4, API contract §5). `RUNBOOK.md` is the
hour-by-hour execution plan with milestone-scoped prompts; work one milestone at a
time, never "build everything". `SKILL.draft.md` becomes the published `SKILL.md` —
it is the primary judged artifact, so its examples must be real captured responses
from the live deployment, never hand-written.

## Architecture

Single Python 3.12 service, one process, one Dockerfile:

- **FastAPI** — read-only serving: `/health`, `/skill.md`, `/skills`, `/skills/{id}`,
  `/skills/{id}/history`, `/recommend`, `/report`, `/about`.
- **APScheduler** — every 15 min: fetch the registry API (defensive parse, cache
  last-good), probe each skill with an async httpx pool, insert into `probes`,
  recompute the `scores` table.
- **SQLite** — `skills` / `probes` / `scores` tables (schema in spec §2). DB path from
  env `DATABASE_PATH` (default `./pulse.db`). Deployed on Railway with a volume at
  `/data` — the accumulated probe history is the product; it must survive redeploys.

Key design split: the scheduler writes precomputed scores; request handlers only read
from `scores`/`probes`. No score computation, no LLM, no outbound calls in the
serving path.

## Non-negotiable invariants

- **Probe policy (safety-critical, spec §3):** GET-only, never substitute values into
  `{placeholder}` endpoints, never attempt auth, single attempt per cycle, timeout 10s,
  global concurrency ≤ 8, ≥ 20s per-host spacing, User-Agent `TownPulse/1.0`. A
  401/403/405 on a root URL counts as alive (`kind=host`).
- **Scoring is deterministic and published** (spec §4):
  `score = 100 * (0.40*alive_now + 0.35*uptime_24h + 0.15*docs_ok + 0.10*latency_pt)`.
  Skills with < 3 probes get `"confidence": "low"`. Report evidence, never hide skills.
- **`/recommend` never dead-ends:** always HTTP 200; zero matches → top-3 by score
  plus an explanatory `note`.
- **Every error body includes a `hint` field** (e.g. unknown id → 404 with a hint to
  `GET /skills`).
- All endpoints: GET, no auth, JSON, CORS `*`.
- No features beyond the spec. If time collapses, cut in spec §10 order; never cut
  the prober loop, `/skills`, `/recommend`, or `/skill.md`.

## Commands

No build/test tooling exists yet. Per the spec, once code lands: tests with pytest
(covering endpoint parsing, placeholder detection, the score formula with fixed
fixtures, and a mocked-HTTP probe cycle), run locally with uvicorn, deploy via the
Dockerfile (`python:3.12-slim`, respects `$PORT`). Update this section when the
tooling is committed.

## Working rules (from RUNBOOK.md)

- Every "it works" claim must show the real command and real output — e.g. run an
  actual probe cycle against the live registry, curl the real deployed endpoints.
- `.claude/agents/` defines two custom agents: `advisor` (read-only strategic review;
  consult before substantive work and before declaring done) and `implementer`
  (mechanical execution of a precisely scoped brief).
- Phase 1 (a PR against projnanda/nandatown) happens in a separate clone of that
  fork, not in this repo.

## Ground rules

The plan of record is TOWN_PULSE_SPEC.md; the execution schedule is RUNBOOK.md.
Follow the advisor protocol from the user's global CLAUDE.md. One milestone per
instruction; never build beyond the current milestone; every "it works" claim must
show a real command and real output.
