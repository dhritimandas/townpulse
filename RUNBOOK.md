# RUNBOOK — NandaHack execution (Thu night + Fri Jul 10 + Sat Jul 11, all times IST)

Files you already have: TOWN_PULSE_SPEC.md, SKILL.draft.md.
Setup for Claude Code: create a fresh project folder `townpulse/`, copy both files into it,
plus your advisor.md and implementor.md. Phase 1 work happens in a separate folder (the
nandatown fork). Run two CC sessions when parallelizing: one on the fork, one on townpulse.

---

## TONIGHT (Thu, ~45 min total)

- [ ] T1. Reply to the organizers' email with your GitHub username (bare handle:
      `dhritimandas`). The rules require this confirmation. 5 min.
- [ ] T2. Confirm the participation/registration Google form is submitted. 5 min.
- [ ] T3. Create Railway account (railway.com → sign in with GitHub). Check that your
      trial/plan allows an always-on service + a volume. If blocked, add the $5 hobby plan
      now, not tomorrow. 10 min.
- [ ] T4. Fork github.com/projnanda/nandatown to your account; clone the fork locally.
      `git clone git@github.com:dhritimandas/nandatown.git` 5 min.
- [ ] T5. Create empty repo `github.com/dhritimandas/townpulse`, clone, drop in the two
      spec files. 5 min.
- [ ] T6. Create a cron-job.org (or UptimeRobot) account — used Friday for keep-alive. 5 min.

---

## FRIDAY

### 09:00–09:20 — Gap verification (do this before anything else)
CC session in `townpulse/`. Paste to the ADVISOR:

> Write and run a quick script: fetch https://nandatown.projectnanda.org/api/skills,
> save the raw JSON to registry_snapshot_2026-07-10.json, print total count, and print
> every skill whose name or description matches any of: uptime, health, monitor,
> monitoring, liveness, alive, probe, ping, reliability, watchdog, status, observability.
> Also print the full field structure of one record so we know the exact schema
> (id, name, description, tags, endpoints, source_url — whatever exists).
> Output a short report. Do not build anything else yet.

DECISION GATE: paste the report to me (this chat).
- No direct competitor → proceed as planned.
- Competitor found → we differentiate (history + evidence + /recommend) or pivot. 15-min
  decision with me, then proceed.
The schema printout also feeds the prober implementation — keep the snapshot file.

### 09:20–10:00 — Phase 1 recon (nandatown fork)
Second CC session in the fork. Paste to the ADVISOR:

> Read this repository end to end: README, the hackathon problem files, the building-block
> modules, the test layout, and the Makefile (find the ci-local target and what it runs).
> Produce: (1) a list of the 12 building blocks with one line each on what they do;
> (2) which existing hackathon PRs (if listed) target which blocks; (3) THREE candidate
> Phase 1 contributions for me, ranked, each with: target block, exact change, the test
> that would fail without the change, estimated effort in hours, and novelty risk (is
> anyone else's open PR doing the same thing — check the GitHub PR list at
> https://github.com/projnanda/nandatown/pulls). Constraints: the contribution must be
> small, rigorous, and thematically adjacent to registry/skills/validation/liveness if
> possible. I have a 3-hour budget for implementation. Do not write code yet.

Paste the three candidates to me. We pick one together (10 min).

### 10:00–13:00 — Phase 1 PR (hard-gated: PR OPEN by 13:00, judges may request fixes)
To the IMPLEMENTOR, after we pick (fill in the chosen candidate):

> Implement candidate <N> exactly as scoped. Rules: (1) branch name
> hackathon/dhritiman-<topic>; (2) TDD — write the failing test first, show me it fails,
> then the fix, then show it passes; (3) run `make ci-local` and do not stop until it is
> fully green; (4) touch the minimum number of files; (5) match the repo's existing code
> style and API conventions exactly — no new dependencies, no refactors, no drive-by
> fixes; (6) write the PR description with sections: Problem / Change / Test (state
> literally what fails without this patch) / Fit (how it follows the block's existing
> API). Boring, precise language. No adjectives, no claims without evidence.

Then YOU (not CC): push branch, open PR on projnanda/nandatown from your fork, paste the
PR description, submit. Check the PR's CI status on GitHub — green before you walk away.
Re-check for judge comments at 15:00, 18:00, 21:00.

### 13:00–15:30 — Town Pulse: prober first (data-moat clock starts on deploy)
CC session in `townpulse/`. To the ADVISOR then IMPLEMENTOR:

> Read TOWN_PULSE_SPEC.md and registry_snapshot_2026-07-10.json in this folder. Implement
> MILESTONE 1 ONLY: the prober and storage. FastAPI app skeleton + APScheduler job per
> spec §2–§3, SQLite schema per §2 (db path from env DATABASE_PATH, default ./pulse.db),
> probe policy EXACTLY per §3 (GET-only, no placeholder substitution, concurrency ≤8,
> per-host ≥20s spacing, 10s timeout, single attempt, User-Agent TownPulse/1.0), score
> computation per §4 written into the scores table each cycle. Plus a /health endpoint
> only. Include a Dockerfile (python:3.12-slim, uvicorn, respect $PORT). Write unit tests
> for: endpoint parsing from registry records, placeholder detection, score formula
> (fixed fixtures), and a mocked-HTTP probe cycle. Run the app locally for one real probe
> cycle against the live registry and show me the resulting row counts and 5 sample rows.

Deploy (you, ~30 min, first time on Railway):
1. Push townpulse repo to GitHub.
2. Railway → New Project → Deploy from GitHub repo → select townpulse. It detects the
   Dockerfile.
3. Service → Variables: add DATABASE_PATH=/data/pulse.db.
4. Service → Settings → Volumes: add volume, mount path /data.
5. Settings → Networking → Generate Domain. Note the public URL.
6. Verify from your phone (different network): https://<url>/health returns ok.
7. Redeploy once and confirm /health's probe_cycles did NOT reset (volume persistence
   check — spec §8; if it reset, fix before continuing).
8. cron-job.org: new job, GET https://<url>/health, every 5 minutes, enabled.

### 15:30–18:30 — Milestone 2: serving API
To the IMPLEMENTOR:

> MILESTONE 2: implement the remaining API per spec §5: /skills, /skills/{id},
> /skills/{id}/history, /recommend, /report, /about (methodology + ethics text from §3
> and §4), /skill.md (serves the SKILL.md file). Requirements: read-only against the
> scores/probes tables (no computation in request path), CORS *, /recommend must NEVER
> return an empty result or non-200 on the happy path (fallback per spec), every error
> body has a "hint" field. Tests: /recommend fallback behavior, unknown id → 404 with
> hint, response shape snapshots for /skills and /recommend. Then run against the real
> local DB and print real responses for: /skills, /recommend?need=escrow,
> /recommend?need=zzzz-nonsense, /skills/<some real id>, /report.

Push → Railway auto-redeploys → verify all endpoints on the PUBLIC url.

### 18:30–20:00 — SKILL.md finalization + acceptance test (this is 80% of the grade)
To the IMPLEMENTOR:

> Take SKILL.draft.md. Replace REPLACE-WITH-LIVE-URL with <public url> everywhere.
> Replace EVERY example response with a real captured response: curl each documented
> example against the public URL right now and paste the actual JSON (truncate arrays to
> the first 1–2 items with no ellipsis inside JSON — keep it valid). Keep the structure
> and wording otherwise identical. Save as SKILL.md in repo root and confirm
> GET <public url>/skill.md serves exactly this content.

Acceptance test — do this yourself, 3 runs minimum: open a COMPLETELY FRESH agent session
(vanilla OpenClaw if you have it set up; otherwise a clean Claude session with no project
context). Paste only SKILL.md content, then exactly:
"Using only the file above, find me a reliable escrow service in Nanda Town and show
evidence that it is currently alive."
PASS = agent calls /recommend, cites score/uptime/alive_now, zero questions back to you.
Any hesitation, wrong URL, or clarifying question = fix the SKILL.md wording, not the
agent. Repeat with need=weather and one nonsense need.

### 20:00–21:15 — Submissions (do not leave this to 21:25)
1. Registry form at nandatown.projectnanda.org/skills: name "Town Pulse"; one-line
   description; tags: monitoring, reliability, registry, discovery, trust; endpoints one
   per line exactly as in SKILL.md (e.g. `GET https://<url>/recommend?need={need}`);
   source_type = URL → https://<url>/skill.md; GitHub username = dhritimandas (bare).
2. Verify: fetch https://nandatown.projectnanda.org/api/skills and confirm your entry
   exists; check your card shows the green reachability badge. If wrong: resubmit (that
   is the official fix path; no edit button).
3. Hackathon Google form: submit/resubmit with both Phase 1 PR link and Phase 2 URLs.
4. Screenshot everything.

### 21:30 — HARD STOP. Phase 1 is final. Phase 2 initial submission locked in.

---

## SATURDAY

- 10:00–14:00 — Polish within Phase 2 only: README of townpulse repo (story: the registry's
  own red badges → we measured → here's the layer; include the /report numbers), /about
  page, optional composition call to TownInspector if trivial, re-run acceptance test.
- 14:00–15:00 — Record demo video per spec §9 (90–120s). Upload. Resubmit Google form with
  video link.
- 16:00 — FEATURE FREEZE. No deploys after this. Keep-alive confirmed running. One last
  public-URL check of every endpoint from your phone.
- 19:00–21:30 — JUDGING WINDOW. Do not deploy, do not restart, do not touch Railway.
  Watch logs read-only if you must.
- 23:30 — Phase 2 window closes. Done.

---

## Standing rules for every CC prompt
- One milestone per session/prompt; never "build everything".
- Every claim of "it works" must be shown: real command, real output.
- No new features not in the spec. If CC proposes one, it goes to the Saturday list.
- If anything blocks >20 min (Railway quirk, registry schema surprise, CI failure),
  stop and bring it to me with the exact error text.
