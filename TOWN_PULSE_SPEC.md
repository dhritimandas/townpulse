# TOWN PULSE — Build Specification (NandaHack, July 2026)

**One-liner:** The live reliability index for Nanda Town. Continuously probes every skill
registered at nandatown.projectnanda.org, maintains uptime/latency history, and answers
one question for any agent: "which skills are actually alive and reliable right now?"

**Why it wins on the rubric** (Phase 2 = 80%, judged on: useful / creative / easy to set up /
agent succeeds from SKILL.md alone):
- Useful: the registry's own badge is a one-shot check at submission time; many cards read
  "couldn't reach link." Every agent consuming the registry needs liveness + reliability.
- Creative: nobody in the 83 current submissions does registry-wide, longitudinal measurement.
  TownInspector = one-shot audit of one SKILL.md on demand. Skill-Router = semantic matching,
  no liveness/evidence. We are a different layer: continuous measurement + evidence.
- Easy: zero auth, all-GET JSON API, one call to value.
- Agent-succeeds: deterministic (no LLM in the serving path, no API keys, no state the agent
  must create first). `/recommend` never dead-ends.
- Data moat: uptime history accrues in wall-clock time. Deploy the prober FIRST, even rough.

---

## 1. Hard deadlines (IST)

| When (IST) | What |
|---|---|
| Fri Jul 10, by ~13:00 | Prober deployed and collecting (data moat starts) |
| Fri Jul 10, by ~17:00 | Phase 1 PR open on projnanda/nandatown (judges reply + may request fixes) |
| Fri Jul 10, 21:30 HARD | Phase 1 final. Phase 2 initial submission: service live, SKILL.md hosted, registry entry shows "link responded", Google form done |
| Sat Jul 11, ~16:00 | Feature freeze. Warm-up pings on. Final SKILL.md dry-run with a fresh agent |
| Sat Jul 11, 19:00–21:30 | JUDGING WINDOW. Service must be up. Touch nothing |
| Sat Jul 11, 23:30 HARD | Phase 2 mods close. Video + resubmitted Google form due |

---

## 2. Architecture

Single Python service. FastAPI + httpx (async) + APScheduler + SQLite. One process, one
Dockerfile, deployed on Railway (hobby plan or trial; NOT Render free — it sleeps).
External keep-alive: cron-job.org (or UptimeRobot) GET /health every 5 min.

```
[APScheduler, every 15 min]
  → GET https://nandatown.projectnanda.org/api/skills   (defensive parse, cache last-good)
  → for each skill: build probe targets (see §3)
  → async probe pool (global concurrency ≤ 8, per-host ≥ 20s spacing, timeout 10s, 1 attempt)
  → INSERT INTO probes(...)
  → recompute scores → scores table (so serving path never computes on the fly)

[FastAPI, read-only]
  /health  /skill.md  /skills  /skills/{id}  /skills/{id}/history  /recommend  /report
```

### SQLite schema
```sql
CREATE TABLE skills   (id TEXT PRIMARY KEY, name TEXT, description TEXT, tags TEXT,
                       source_url TEXT, endpoints_raw TEXT, first_seen TEXT, last_seen TEXT);
CREATE TABLE probes   (id INTEGER PRIMARY KEY, skill_id TEXT, target TEXT, kind TEXT,
                       ts TEXT, ok INTEGER, status_code INTEGER, latency_ms INTEGER,
                       error TEXT);
CREATE TABLE scores   (skill_id TEXT PRIMARY KEY, alive_now INTEGER, uptime_24h REAL,
                       uptime_all REAL, p50_latency_ms INTEGER, docs_ok INTEGER,
                       n_probes INTEGER, score REAL, updated_at TEXT);
CREATE INDEX ix_probes_skill_ts ON probes(skill_id, ts);
```
Persist the SQLite file on a Railway volume. The history IS the product — losing it on
redeploy destroys the moat. Verify volume persistence on the first deploy.

## 3. Probe policy (safety-critical — this goes verbatim in README + SKILL.md footer)

We only ever issue safe, read-only requests:
1. `source_url` of the SKILL.md (GET) — "docs reachable".
2. Root of each distinct endpoint host, e.g. `https://app.onrender.com/` (GET) — "host alive".
3. Declared GET endpoints **with no `{placeholder}`** (GET, as declared).
4. NEVER: POST/PUT/DELETE/PATCH, never placeholder substitution, never auth attempts,
   never retries in the same cycle.
- User-Agent: `TownPulse/1.0 (NandaHack participant; +<our-url>/about)`
- Timeout 10s. Latency recorded from a single attempt. A 401/403/405 on a root URL counts
  as ALIVE (host answered) but is flagged `kind=host` not `kind=endpoint`.
- Include ourselves in the probe set (we appear in the registry too — honest, and funny).

## 4. Scoring (deterministic, documented, no magic)

```
docs_ok    = skill.md fetchable AND ≥1 endpoint parseable         (0 or 1)
alive_now  = any successful probe in the most recent cycle         (0 or 1)
uptime_24h = successful probe cycles / total cycles, last 24h      [0,1]
latency_pt = clamp(1 - p50_latency_ms/5000, 0, 1)                  [0,1]

score = 100 * (0.40*alive_now + 0.35*uptime_24h + 0.15*docs_ok + 0.10*latency_pt)
```
Skills with n_probes < 3: score reported with `"confidence": "low"`. Never hide anyone;
report evidence, not verdicts. Formula published at /about and in README.

## 5. API contract (all GET, no auth, JSON, CORS *)

`GET /health` → `{"status":"ok","skills_tracked":91,"probe_cycles":128,"since":"2026-07-10T08:00:00Z"}`

`GET /skill.md` → text/markdown (the SKILL.md itself; same content also at raw GitHub URL)

`GET /skills` → `{"count":91,"skills":[{"id":"...","name":"...","score":87.5,"alive_now":true,
"uptime_24h":0.96,"p50_latency_ms":412,"tags":["escrow"]}, ...]}` sorted by score desc.

`GET /skills/{id}` → full score record + `latest_evidence`: list of last-cycle probes
(target, status_code, latency_ms, ts).

`GET /skills/{id}/history?hours=24` → probe cycles time series.

`GET /recommend?need=<free text>&min_uptime=0.0&limit=3` →
```json
{"need":"escrow","matches":[{"id":"...","name":"...","score":91.0,"alive_now":true,
  "why":"tag match: escrow; uptime_24h 0.98; p50 320ms",
  "endpoints":["POST https://.../escrow"],"skill_md":"https://.../skill.md"}],
 "note":null}
```
Matching: lowercase token match over tags → name → description (in that priority), rank by
(alive_now, score). **Never dead-end:** if zero matches, return top-3 by score with
`"note":"no direct match for '<need>'; returning most reliable live skills"`. Always 200.

`GET /report` → registry-wide summary: total, % alive now, % ever-dead, top 10, worst 10,
median latency. (This powers the demo video: "X% of the registry is unreachable right now.")

Error handling: unknown id → 404 with `{"error":"unknown skill id","hint":"GET /skills for ids"}`.
Every error body includes a `hint`. Judges' agent must never be stuck.

## 6. SKILL.md rules (this file is 80% of the grade — treat as the product)

From the organizers, verbatim requirements: title line + one sentence; Base URL on its own
line; per endpoint: method+path, one sentence, one example curl, one example response;
numbered plain-language "How the agent should use this". Their guidance: "one real curl call
and its real response is worth more than a paragraph"; "clear, boring, precise, technical
language"; "leave absolutely no room for guesswork".

Rules we add:
- Every example response is a REAL captured response from the live URL, not hand-written.
- No placeholders the agent must resolve except `{id}` and `{need}`, both explained with a
  concrete filled-in example.
- Section order: what it is → base URL → the ONE primary workflow (recommend) → other
  endpoints → numbered usage steps → probe-ethics footer.
- Acceptance test (mandatory, iterate until pass): fresh agent session (vanilla OpenClaw or
  a clean Claude session), paste ONLY the SKILL.md, instruct: "Using only this file, find me
  a reliable escrow service in Nanda Town and show evidence it is alive." Agent must succeed
  with zero follow-up questions. Run this at least 3 times Friday night / Saturday.

## 7. Phase 1 PR (20%) — plan

Constraint: improve one of the 12 building blocks in projnanda/nandatown, or add one.
Branch: `hackathon/dhritiman-<topic>` (real, descriptive). Must include a test that fails
without the change; `make ci-local` green BEFORE push.

Decision procedure (first hour tomorrow):
1. Clone repo, run it, list the 12 building blocks.
2. Pick the block closest to registry / skills / validation. Candidate contributions, in
   order of preference:
   a. **Endpoint/SKILL.md validator utility**: parse `METHOD URL` endpoint lines, validate
      scheme/method/URL, structured errors. Directly reinforces Town Pulse's story.
   b. **Liveness-check helper** for registry entries (pure function + mocked-HTTP tests).
   c. If (a)/(b) don't fit any block's API: smallest correctness fix in the registry-adjacent
      block, with a rigorous failing-then-passing test.
3. PR description template: Problem (one paragraph, cite the observed defect) → Change →
   Test (state exactly what fails without the patch) → How it fits the block's existing API.
   Boring, specific, zero adjectives.
4. Open the PR by ~17:00 IST Friday. Watch for judge replies; fix same-day.

## 8. Deployment & ops

- Railway: GitHub-linked deploy, Dockerfile, attach a volume for SQLite, set `PORT` env.
- Verify from a phone/other network: every endpoint on the PUBLIC url, not localhost.
- Keep-alive: external cron GET /health every 5 min from Friday night through Saturday 21:30 IST.
- Registry submission: form at nandatown.projectnanda.org/skills; endpoints one per line as
  `GET https://.../recommend?need={need}` etc.; source_type=url pointing at /skill.md
  (hosted link gets the reachability badge; pasted text does not). GitHub username field =
  bare handle `dhritimandas` (this links Phase 1 ↔ Phase 2). No edit button — resubmitting
  is the normal fix path.
- After submit, verify via `GET https://nandatown.projectnanda.org/api/skills` that our
  entry exists and badge flips to "link responded".

## 9. Demo video (required, ≤ Sat 23:30 IST; doesn't affect score but mandatory)

90–120s, screen recording: (1) the registry page with red "couldn't reach link" cards —
the problem, visible on the organizers' own site; (2) `GET /report` — measured: "as of now,
N% of registered skills are unreachable"; (3) a fresh agent given only SKILL.md completing
"find me a reliable X" with evidence; (4) one sentence: continuous measurement layer for the
NANDA registry quilt — infrastructure every other submission benefits from.

## 10. Cut-list (if time collapses, cut from the bottom)

1. /report extras and worst-10 list
2. /skills/{id}/history endpoint (keep data collection — cheap; cut only the endpoint)
3. latency component of the score (fold to uptime-only)
NEVER cut: prober loop, /skills, /recommend, /skill.md, keep-alive, SKILL.md dry-runs.

## 11. Risks

- Registry API shape drift → defensive parsing + last-good cache; log & skip bad records.
- New competing submissions before Saturday → re-scan /api/skills Friday night; our moat is
  accumulated history, which is time-locked.
- Railway trial limits → verify tier allows always-on + volume within the first hour;
  fallback: Fly.io (needs card) or a $5 plan. Decide once, immediately.
- Probing complaints → ethics footer, identifying UA, conservative rates. We probe only
  what participants publicly declared for exactly this purpose.
