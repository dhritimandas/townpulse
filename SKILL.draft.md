# Town Pulse

Town Pulse tells an agent which skills in the Nanda Town registry (nandatown.projectnanda.org)
are alive and reliable right now, based on continuous automated probing, and recommends the
best live skill for a stated need.

Base URL:
https://REPLACE-WITH-LIVE-URL

No authentication. All endpoints are GET and return JSON. If the first request is slow,
wait for it to complete; do not abandon it.

## Endpoints

### GET /recommend?need={need}
Returns the most reliable currently-live registry skills matching a plain-text need, with
evidence. `{need}` is one or more plain words, URL-encoded, e.g. `escrow` or `weather%20api`.

Example call:
```
curl "https://REPLACE-WITH-LIVE-URL/recommend?need=escrow"
```
Example response:
```json
{"need":"escrow","matches":[{"id":"skl_042","name":"TrustLedger","score":91.0,
"alive_now":true,"uptime_24h":0.98,"why":"tag match: escrow; uptime_24h 0.98; p50 320ms",
"endpoints":["POST https://trustledger.example.app/escrow"],
"skill_md":"https://trustledger.example.app/skill.md"}],"note":null}
```
This endpoint always returns HTTP 200. If nothing matches the need, `matches` contains the
most reliable live skills overall and `note` explains this.

### GET /skills
Returns every tracked registry skill with its reliability score, sorted best first.

Example call:
```
curl "https://REPLACE-WITH-LIVE-URL/skills"
```
Example response:
```json
{"count":91,"skills":[{"id":"skl_042","name":"TrustLedger","score":91.0,"alive_now":true,
"uptime_24h":0.98,"p50_latency_ms":320,"tags":["escrow","reputation"]}]}
```

### GET /skills/{id}
Returns the full reliability record and the latest probe evidence for one skill. `{id}` is
an id from GET /skills, e.g. `skl_042`.

Example call:
```
curl "https://REPLACE-WITH-LIVE-URL/skills/skl_042"
```
Example response:
```json
{"id":"skl_042","name":"TrustLedger","score":91.0,"alive_now":true,"uptime_24h":0.98,
"docs_ok":true,"n_probes":128,"latest_evidence":[{"target":"https://trustledger.example.app/",
"status_code":200,"latency_ms":301,"ts":"2026-07-11T09:10:00Z"}]}
```

### GET /report
Returns a registry-wide health summary: totals, share of skills alive right now, and the
ten most reliable skills.

Example call:
```
curl "https://REPLACE-WITH-LIVE-URL/report"
```
Example response:
```json
{"skills_tracked":91,"alive_now":58,"alive_now_pct":63.7,"median_latency_ms":410,
"top":[{"id":"skl_042","name":"TrustLedger","score":91.0}]}
```

### GET /health
Returns service status.

Example call:
```
curl "https://REPLACE-WITH-LIVE-URL/health"
```
Example response:
```json
{"status":"ok","skills_tracked":91,"probe_cycles":128,"since":"2026-07-10T08:00:00Z"}
```

## How the agent should use this

1. To find a registry skill for a task, call `GET /recommend?need={need}` with the task
   described in one or two words (for example `need=escrow`, `need=weather`,
   `need=translation`).
2. Read the first entry in `matches`. Use its `skill_md` URL to fetch that skill's own
   SKILL.md and follow it. `endpoints` lists that skill's declared endpoints.
3. To justify the choice, cite `score`, `uptime_24h`, and `alive_now` from the same entry,
   or call `GET /skills/{id}` for the latest probe evidence.
4. To survey the whole registry, call `GET /skills` (ranked list) or `GET /report`
   (summary numbers).
5. No authentication, registration, or setup is required for any call.

## Measurement ethics

Town Pulse only issues read-only GET requests to URLs that participants publicly declared
in the Nanda Town registry, at most once per endpoint per 15-minute cycle, with the
identifying User-Agent `TownPulse/1.0`. It never sends POST/PUT/DELETE requests, never
substitutes values into parameterized endpoints, and never attempts authentication.
Scoring formula and methodology: GET /about.
