# Choosing terminal agents for agent-runner

Goal: the runner drives **any** headless coding agent, so a team can use whatever login it already has:
GitHub Copilot (github.com), Copilot on **GHE** (enterprise host), ChatGPT/**Codex** subscription,
Anthropic/Claude, or a plain API key. This page lists the candidates, what the runner needs from each,
and the tests that pick a winner. `tests/agent_matrix.py` runs them.

## What the runner needs from a backend

Taken from what `runner.py` does today for Claude and Pi:

| # | Capability | Why | Runner code |
|---|------------|-----|-------------|
| R1 | Headless one-shot run, exits when done | slots and fix sessions run unattended | `agent_flags`, `fix_cmd` |
| R2 | Prompt from a file (or stdin) | Windows 32 KB / Linux 128 KB arg limits | `agent_cmd`, `agent_argv` |
| R3 | Auto-approve tools, no questions | nobody is at the pane | `--approve`, `bypassPermissions` |
| R4 | Choose model per run | `model` / `fix_model` | `--model` |
| R5 | Caller-chosen session id + resume | `resume ID`, restart adoption, cut-off resume | `--session-id`, `transcript()` |
| R6 | Machine-readable transcript (JSONL) at a known path | `stats`, `last_words`, `cut_off`, `stalled` | `entries()` / `pi_entry()` |
| R7 | Restrict tools (shell/read/edit/write), no MCP/extensions | `lean = true` | `lean()` |
| R8 | Meaningful exit codes; errors distinguishable transient vs auth/billing | resume vs report to human | `NOT_RESUMED` |
| R9 | Works on Windows (wt/console) and Linux (tmux) | both platforms ship | `plat` |
| R10 | Corporate TLS (system CA) | GHE behind interception | `NODE_USE_SYSTEM_CA=1` |

## Candidates

Logins marked **?** are claims to verify with test A1–A4, not facts.

| Agent | Install | Copilot | Copilot GHE | Codex (ChatGPT) | Anthropic | API keys | Headless | Notes |
|-------|---------|---------|-------------|-----------------|-----------|----------|----------|-------|
| **Pi** (`pi`) 1.4.0 — *done* | npm `@earendil-works/pi-coding-agent` | yes | yes (`/login`, enterprise host) | yes? (`openai-codex`) | yes | many | `--print`, `--session-id`, `@file` | already a backend here |
| **Copilot CLI** (`copilot`) 1.0.10x | winget / npm `@github/copilot` | yes | yes? (`GH_HOST` / login host) | no | Copilot models only | no | `-p`, `--allow-all-tools`, `--session-id`, `--resume`, `--output-format json` | first-party; installed here |
| **Codex CLI** (`codex`) 0.165 | npm `@openai/codex` | no | no | yes | no | OpenAI, OSS via `--oss` | `codex exec --json`, `codex exec resume <id>` | sandbox modes; best for Codex plans |
| **opencode** (`opencode`) 1.19 | npm `opencode-ai` | yes | yes? (enterprise URL at login) | yes? | yes? | many (models.dev) | `opencode run --format json`, `--session`, `--model provider/id` | multi-provider like Pi |
| **Arctic** (`arctic`) | npm `@arctic-cli/arctic` (native binary, opencode-style packaging, no README in the tarball) | ? | ? | ? | ? | ? | ? | unvetted: verify publisher, licence and source before installing on a work machine |
| **Crush** (`crush`) 0.99 | npm `@charmland/crush` | ? | ? | ? | yes | many | `crush run` | Charm; check JSON/session support |
| **Claude Code** (`claude`) | npm | no | no | no | yes | Bedrock/Vertex | current default | baseline |
| Gemini CLI, Goose, Aider | various | no | no | no | partly | yes | yes | lower priority: no Copilot/Codex logins |

Shortlist for "works with any AI": **Pi** and **opencode** (multi-provider, Copilot + GHE + Codex
in one tool), with **Copilot CLI** and **Codex CLI** as first-party fallbacks for their own logins.
Arctic stays on the list only if A0 passes.

## Tests

Tiers: **static** (no login, no network), **auth** (login present, no model call), **live** (spends
tokens on tiny tasks in a temp repo). `python tests/agent_matrix.py [--live] [agents…]` prints a matrix.

### A — Install and auth
- **A0 provenance**: package publisher, licence, source repo, postinstall behaviour (Arctic, Crush).
- **A1 Copilot github.com**: log in, list models, one-word prompt succeeds.
- **A2 Copilot GHE**: same with the enterprise host; behind corporate TLS with `NODE_USE_SYSTEM_CA=1`
  and *without* disabling verification.
- **A3 Codex/ChatGPT**: subscription login (not API key), one prompt succeeds.
- **A4 non-interactive auth check**: a command that reports logged-in/out without a prompt or a
  browser (`pi auth check`, `copilot` status?, `codex login status`, `opencode auth list`).
- **A5 secrets**: tokens stay in the agent's own store; nothing lands in the repo, `.runner/`, or logs.

### B — Headless contract (static: from `--help`; live: confirmed)
- **B1** one-shot flag exits with code 0 after the answer (R1).
- **B2** 200 KB prompt via file/stdin reaches the model intact (R2) — ask it to echo a marker at the end.
- **B3** writes a file and runs a shell command with no approval prompt (R3); stdin is `/dev/null`.
- **B4** `--model X` honoured; a bad model id fails fast with nonzero exit (R4, R8).
- **B5** preset session id, then resume it and the model remembers a fact from turn 1 (R5).
- **B6** transcript found at a predictable path; has per-call usage and timestamps (R6).
- **B7** tool allowlist: a denied tool (e.g. web fetch) is refused (R7).

### C — Failure behaviour
- **C1** network down mid-run → nonzero exit, transcript error text classifies as transient.
- **C2** logged out / expired token → nonzero exit, classifies as auth (not resumed).
- **C3** rate limit / quota → classifiable; reset time parseable if offered.
- **C4** SIGTERM / console close → no orphan processes (`end_orphans`).

### D — Runner integration (live, in a temp repo with a `plan/TODO.md`)
- **D1** `agent-runner run once` with `slots = 1` finishes one task: commit on `task/<ID>`, `done` called.
- **D2** `slots = 3`, three independent tasks, parallel worktrees, all merged.
- **D3** a forced merge conflict is fixed by the fix session (`fix_model`).
- **D4** `agent-runner resume ID` continues a cut-off session.
- **D5** Windows `wt` and Linux `tmux` both pass D1.

### E — Quality and cost (same 5-task benchmark per agent × model)
- Tasks: rename across files, add a unit test, fix a failing test, small feature, doc update.
- Score: tasks merged green, wall time, model calls, peak context (`stats()`), retries, human fixes.
- Run each agent with the *same* model where possible (e.g. Claude Sonnet via Copilot) so the
  agent harness, not the model, is what is compared.

## Results

### 2026-10-30, Windows 11, Copilot (github.com) login, model Claude Haiku 5.5

| Check | Pi 1.4.0 | Copilot CLI 1.0.103 |
|-------|----------|---------------------|
| Static flags (R1–R7) | all present | all present |
| A4 non-interactive auth check | `pi auth check --provider github-copilot --json` → ready | none found (verify) |
| B1 answer and exit | pass 1.7 s | pass 7–19 s |
| B3 edit file / run shell unprompted | pass 2.8 s / 3.0 s | pass 8.5 s / 10–12 s |
| B2 150 KB prompt | pass (`@file`) | pass via **stdin** only (`-p` is argv) |
| B4 bad model → exit 1 | pass (provider 400) | pass (rejected before the call) |
| B5 preset id + resume remembers | pass (`--session-id` + `--session-dir`) | pass (`--session-id`, `--resume=<id>`) |
| B6 transcript | `<session-dir>/*_<id>.jsonl`, usage per call | `~/.copilot/session-state/<id>/events.jsonl`, `session.usage_record` |
| D1 `run once` on examples/hello | **pass**: G1 done, gate green, pushed, 20 s, 5 calls, 6k peak | not wired yet |

Notes: Copilot CLI on Windows keeps a process in the cwd briefly after exit, so temp-dir cleanup can fail
(`end_orphans` should cover it in the runner). Pi prints a harmless "No project session found with id"
warning when the runner presets a new session id. Not yet tested: GHE host (A2), Codex login (A3),
failure classes C1–C3, parallel slots (D2), Codex CLI, opencode, Arctic, Crush.

## Pass bar for a backend

Must: R1–R6, R8, R9, A4, A5, B1–B6, C2, D1, D4. Should: R7, R10, C1, C3, D2, D3, D5.

## Integration shape

`backend` selects a class in `runner.py`'s `BACKENDS`: `Claude`, and `Pi` as a subclass of it. A new
backend subclasses `Claude` and overrides what differs: `flags`, prompt passing (`cmd`/`argv`),
`fix_cmd`, `find_transcript`, `entry` (its transcript records in Claude's shape, error classification
included), `limits` and `report_exit`; then `config.py` accepts its name.
