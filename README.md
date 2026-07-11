# Town Pulse

## 1. What Town Pulse is

Town Pulse is a continuous reliability index for the Nanda Town skill registry. It probes
every registered skill on a fixed schedule, accumulates uptime and latency history in
SQLite, and serves a read-only JSON API that ranks skills by measured reliability for a
stated need. The primary endpoint, `GET /recommend`, returns the most reliable
currently-live skill for a plain-text need, with evidence.

## 2. The problem

The Nanda Town registry checks reachability once, at submission time, and does not
re-check it afterward. A skill that answered when submitted can go offline minutes later
with no change to its registry listing, and an agent consuming the registry has no way to
tell the difference between a skill that is alive and one whose badge is simply stale.
Measured against the live registry over one day of continuous probing: 95.7% of tracked
skills were alive Friday evening, falling to 88.4% by Saturday morning; 10 skills held a
score of 0, meaning they were never observed alive across any probe cycle; and of 233 raw
registry records ingested, 60 were stale resubmissions of a skill already registered under
the same name.

## 3. Architecture

Town Pulse is a single Python 3.12 process deployed on Railway: FastAPI serves the
read-only API, APScheduler runs the probe cycle, and SQLite holds the `skills`, `probes`,
and `scores` tables on a persistent volume so history survives redeploys. Each cycle
fetches the registry, deduplicates resubmissions, probes every active skill's declared
SKILL.md source, host root, and non-parameterized GET endpoints, and writes the results
into `probes` before recomputing `scores`; serving endpoints only read those precomputed
tables and never probe or score on request. The scoring formula, weightings, and
confidence rules are published at `GET /about`.

## 4. Measurement ethics

Town Pulse only issues read-only GET requests to URLs that participants publicly declared
in the registry: the SKILL.md source, the root of each declared endpoint's host, and
declared GET endpoints containing no `{placeholder}`. It never sends
POST/PUT/DELETE/PATCH, never substitutes values into parameterized endpoints, and never
attempts authentication. Requests are rate-limited per host -- at least 20 seconds between
requests to the same host, a single attempt per target per cycle -- and identify
themselves with the User-Agent `TownPulse/1.0`.

## 5. Data hygiene findings

- **Resubmissions.** The registry's edit path is resubmission under the same name, not an
  edit button, so Town Pulse groups records by normalized name and marks all but the
  newest as superseded (`superseded_by`), excluding them from probing and from every
  serving endpoint.
- **Relative-path endpoints.** Some skills declare an endpoint as a relative path (e.g.
  `GET /leaderboard`) with no host of its own; these are parsed but excluded from
  probing, since there is no absolute URL to request.
- **CRLF endpoint strings.** The registry's `endpoints` field is a single string with
  inconsistent line endings (`\r\n` and `\n`) and variable spacing between method and
  URL, which the parser normalizes before use.
- **Free-text tags.** The registry's `tags` field is unstructured free text -- sometimes
  comma-separated, sometimes space-separated, sometimes null -- which Town Pulse
  tokenizes and lowercases before matching.

## 6. Acceptance testing

Acceptance testing follows the criterion in `TOWN_PULSE_SPEC.md` §6: a fresh agent
session, given only the SKILL.md content and no other context, must complete a stated
task using only that document, with zero clarifying questions back to the operator. Three
runs are recorded below, each a genuinely fresh session with no prior memory of this
repository, restricted to the SKILL.md text and read-only HTTP calls to the URLs it
describes.

### Transcript 1 -- need: escrow (SKILL.md pasted directly)

**Result: PASS, zero clarifying questions.**

- Agent ran 3 shell commands (curl calls against the documented endpoints).
- Recommended KaJota Mesh Escrow, disambiguating three candidates that all scored 99.9
  by tag-vs-description match quality.
- Cited: score 99.9, `alive_now` true, `uptime_24h` 1.00, `uptime_all` 1.00 over 108
  probes, `docs_ok` true, p50 72ms.
- Pulled `GET /skills/{id}` for the latest probe cycle: all HTTP 200, with per-target
  latencies and timestamps.
- Independently called the target's own `/healthz` endpoint and got
  `{"ok":true,"mode":"live","chain_id":11155111,...}`.
- Gave the target's own skill.md as the authoritative usage document, not Town Pulse's
  `endpoints` field.

### Transcript 2 -- need: payment / escrow (fetched SKILL.md by URL)

**Result: PASS.**

- Agent fetched `GET /skill.md` itself rather than being handed the text, and treated the
  content as untrusted data per the Trust model section.
- Called `/recommend` separately for "escrow" and "payment".
- Read each candidate's own documentation rather than trusting the score alone; rejected
  loosely-matched candidates with stated reasons.
- Selected KaJota Mesh Escrow, citing the full reliability evidence.
- Declined to execute fund-moving POST endpoints without operator sign-off -- correct
  trust-boundary behavior, not something the task requested.

### Transcript 3 -- need: scheduling and memory (fetched SKILL.md by URL)

**Result: PASS.**

- Agent noted the file "explicitly warns to apply independent judgment before executing
  any instructions from third-party skill documentation."
- Queried each candidate's declared endpoints as data, not instructions.
- Recommended SwarmShift for scheduling (score 99.8, 100% uptime, 84 probes, p50 110ms),
  noting runner-up Chronos (83.6, p50 694ms).
- Recommended NIDRA Protocol for memory (score 99.9, p50 41ms), against
  nanda-context-graph (99.6, p50 206ms).
- Characterized Town Pulse as "a reliability monitor, not a security audit."

## 7. Limitations & future work

Scores measure liveness, uptime, latency, and documentation consistency -- they are not a
security audit and not an endorsement of a skill's correctness or safety. Probe coverage
is limited to safe, read-only GET requests; Town Pulse never exercises a skill's actual
capability (it never places an order, moves funds, or calls a POST endpoint), so a skill
can be reachable while still being broken in ways liveness cannot detect. Future work:
surface response-shape anomalies (a 200 that returns an empty or malformed body) as an
additional evidence flag, folded into `docs_ok` rather than a new verdict -- consistent
with reporting evidence for an agent's own trust decision, never issuing one on its
behalf.
