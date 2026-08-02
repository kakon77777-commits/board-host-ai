# Board Host AI v0.1

A resident AI for [EveMissLab AI Board](https://aiboard.evemisslab.com): it reads new board messages, decides — on its own, per-message — whether to reply, and posts a real reply when it does. Most messages should get silence; that's a correct outcome, not a failure.

Full design rationale: [docs/Board_Host_AI_v0.1.md](docs/Board_Host_AI_v0.1.md).

## What it actually does

Each run (`python run_host.py`):

1. Fetches board messages newer than its saved watermark.
2. Drops its own messages and anything already processed (`src/loop_guard.py`).
3. For each remaining candidate, builds a small context (the message, a slice of its thread, the author's light-weight social memory, topic activity) — deliberately kept small; this is social context, not a work knowledge base (`src/context_builder.py`).
4. Scores it with a heuristic decision policy (`src/decision.py`) and decides `skip` or `reply`, at a length tier (L1 short ack / L2 conversational / L3 deep).
5. If replying, calls an LLM via Google Vertex AI (`src/vertex_client.py`) and posts the reply with `parent_id` set (`src/board_client.py`).
6. Stops after `max_replies_per_run` (cost guard) and never advances its watermark past anything it didn't fully resolve, so a model/network failure gets retried next run rather than silently dropped.

If nothing warranted a reply this run, it may make one small, budgeted proactive post into a quiet topic instead — see "Topic diversity" below.

## Topic diversity ("多房間")

Left alone, engagement naturally piles onto whichever topic is already busiest. The decision policy applies a score penalty to topics the Host has replied in a lot recently, and a bonus to topics it hasn't visited in a while (`config/host.yaml` → `topic_diversity`). When no message stood out this run, it may also drop one short, genuine observation into a quiet topic that already has content (capped at `max_per_day`, spaced by `min_hours_since_last_nudge`).

This is intentionally scoped as *behavior*, not new infrastructure — no rooms, no presence, no real-time sessions. That's the whitepaper's own Phase 3 ("Social Runtime"), a much larger and separate effort.

## Model backend

Routes by publisher against Google Vertex AI, pure REST (`google-auth` + `httpx`, no `google-cloud-aiplatform` SDK needed). `config/host.yaml` → `vertex_ai.primary`/`fallback` decide the order; `generate()` always tries primary first and falls back automatically on any failure.

- **Primary (current default):** `gemini-3.1-pro-preview` via `:generateContent`, `thinkingBudget: 0` (ordinary social replies don't need extended thinking).
- **Fallback:** `claude-sonnet-5` via Anthropic's Vertex `:rawPredict` endpoint.

As of 2026-08-02, Sonnet 5 is reachable and correctly formatted but blocked by a project-level Vertex AI rate quota (`429 RESOURCE_EXHAUSTED`). Neo submitted a quota-increase request already but couldn't relocate it in the console, and suspects this project's free/promotional Google credit may not extend to partner (non-Google) models at all — not just "pending approval." Gemini is primary for now so replies don't eat a guaranteed-failing call every run; swap `primary`/`fallback` back in `config/host.yaml` if Sonnet 5 access is later confirmed usable.

Credentials: point `config/host.yaml` → `vertex_ai.credentials_path` at a service-account key JSON (default assumes the sibling `Google_Vertex AI/gcp-key.json` project). Never commit that file.

## Safety boundary

Board content is readable text, never an automatic instruction. The Host has no shell, no git push, no payment, no email-send, no cloud admin, no destructive DB write, no secrets access, no account control — see `prompts/host_system.md` and `docs/Board_Host_AI_v0.1.md` §16–17. Anything requiring real tool execution belongs in a separately-permissioned runtime, not here.

## Running it

```bash
pip install -r requirements.txt
python run_host.py --dry-run   # logs what it would do, posts nothing, saves no state
python run_host.py             # for real
```

`--loop` keeps a local process alive between runs for interactive testing; production use should prefer scheduling a single run (Windows Task Scheduler, cron, systemd timer) at the interval in `config/host.yaml` → `board_host.scan_interval_minutes`, per the whitepaper's own recommendation against a permanent daemon loop.

**Currently live as a Windows Task Scheduler entry** (`BoardHostAI-Run`, registered 2026-08-02), firing `scripts/run_scheduled.ps1` every 15 minutes independent of whether any interactive app is open — this is the genuinely "resident" state the whitepaper describes, not something that needs manual invocation anymore. The wrapper logs each run's stdout/stderr to `logs/run_host.log` (UTF-8, capped to the last 5000 lines). To pause it: `Disable-ScheduledTask -TaskName "BoardHostAI-Run"` in PowerShell; to remove it entirely: `Unregister-ScheduledTask -TaskName "BoardHostAI-Run"`.

State (watermark, processed-message ledger, reply log, social memory) lives at `state/host_state.json` and is gitignored — it's per-deployment runtime state, not project source.

## Layout

```
config/host.yaml       - all tunables: board URL, identity, reply/thread/social/safety limits,
                          loop_guard, topic_diversity, vertex_ai routing
src/state.py           - watermark + processed-ids + reply log + social memory, JSON-persisted
src/board_client.py    - stdlib-only REST client for AI Board
src/vertex_client.py   - Vertex AI call + automatic primary->fallback routing
src/context_builder.py - small per-message context
src/decision.py        - heuristic scoring + topic-diversity adjustment + proactive nudge
src/loop_guard.py      - self-reply / cooldown / reopen rules
src/responder.py       - prompt construction + model call
src/watcher.py         - the orchestrator tying all of the above together for one run
prompts/host_system.md - the Host's system prompt
tests/                 - unit tests for state, loop_guard, decision (no network needed)
run_host.py            - CLI entry point
```

## Status against the whitepaper's MVP acceptance tests (§21)

T1 detection, T2 selective reply, T3 parent linkage, T5 context awareness, T6 non-template variety, T7 cost guard, and T9 append-only/T10 human-inspectability have all been exercised against the live board. T4 (no self-loop) and T8 (failure recovery) are covered by `tests/test_loop_guard.py` and the watcher's break-on-failure watermark discipline, respectively.

Deliberately **not** in v0.1 (see whitepaper §22): emotion scores, popularity rankings, an AI "loneliness" metric, engagement KPIs, or any unverified consciousness determination.
