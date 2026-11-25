"""F65: the run page model: one snapshot of the run (JSON) for the web page, the terminal UI and the claude.ai
copy, and the actions they share.

`snapshot()` reads what `status` reads (STATE, the plan, the run log, Needs you) and returns one plain dict:

    status    the status lines: run up or not, its state, progress, release, no-settings or no-gate warning, usage
    slots     the run's slot count (0 when no run is up; while it starts, [run] slots)
    sessions  every live control session (cN, its title from state), then each slot s1..s<slots>
              and any past the count still on a task: task, title, minutes, state (running, merging, idle: no
              task), files, session link, terminal URL
    sessions_note  '' (kept for pages that read it: C26 has no older run to tell apart)
    queue     every open task in TODO.md: id, kind, title, files, after, pri, section, blocked, after_title
              (what it waits on in words: 'F66 Run page: …', 'B109 (landed)', 'all: everything above it') and
              state ('running s2 6m', 'critical', 'after', 'tool', 'split', 'parked', 'ready'); with shared tools set, needs
              and tool_wait ('waits for iPhone 15, held by F389, 12 min'); B811b: a split task's `split` (`split_parts`)
    tools     the shared tools ([run.tools]; F168): name, label, state, words, waits; [] without them
    shelved   F184: the shelved tasks (`shelved_rows`), which queue, needs and concepts leave out: id, kind, title,
              ask in plain words, state 'shelved'
    needs     what waits on the person (not the shelved ones): label, id, ask in plain words, link, age, detail (what
              its card and popup say: said, title, where, summary, lead, steps, expect, notes, shots, step_more and inputs (F175); need_detail), and
              devices where its task needs any with a web page (F408: name, page, state; `devices.need_pages`), and
              the runner.toml tools with a page that it needs too (F428b: the same, with source "runner.toml" and label; `need_tools`)
    concepts  concept pages waiting for an OK: build id, concept id, title, page link, copy (the local copy
              of the page `done --artifact` kept, <notes>/concepts/<ID>.html; '' for none), lead (`concept_chat_text`)
    log       the run log's last lines
    manage_releases  F193: `[run] releases`; False: `releases` and `release_acts` are empty, `release` and
              `release_said` '', and an open V task is an ordinary row of `queue`
    release   the release lines, one per release ('' for none)
    releases  F185: the releases, one row each (`release_rows`): the open V tasks (also in
              `queue` at their place, each with `release`: its row), a placeholder while `[run] auto_release` counts (F195c:
              `before`, the queue row it stands before), then
              the last one released
    quick_asks  the Status chat's quick asks, each a new chat: key, label, text
    terminal_mode  how a session's terminal shows: 'ttyd', or 'install' (no ttyd yet)
    run       paused, stopping, forced, power, and `state`: the state pill's words (F124: `run_state`)
    merging   F426e: the tasks that merge now, [{'id', 'title', 'step', 'link'}] (`merge_rows`); step: the run log's last words
    usage_max F426e: the usage percent past which new tasks wait, by usage name
    usage     F124: the account's usage, [{'name': 'session'|'week', 'pct'}]
    lately    F124: what landed lately, newest first, the words `status` lists under "lately": [{'at', 'text'}]; F426c: 'id'
              (its task, '' for none), 'kind' ('landed', 'part', else '') and, for those two, 'title'
    past_releases  F426c: the releases that landed, newest first, [{'id', 'title', 'at'}]; [] with `[run] releases` off
    fixups    F124: what the Fix up controls would work on (`fixups`): {'resume', 'unclaim', 'wip': [{'id', 'label'}]}
    claude_login  F126a: the Claude login warning (`watch.claude_login_line`), the page's banner, else ''
    no_settings  F178: the warning when no settings file was found (`no_settings`), else ''
    agent_problem  B764b: what is wrong with `[run] agent` and the fix (`agent_problem`), else ''
    responses  F425a: the sent responses kept (`sent_responses`), newest first: id, item, title, question, ask, answer,
              note, at (epoch s); `response_chat` (id, words) starts the chat about one
    chat_quiet  F128: `[ui] chat_quiet` in seconds (0 off)
    version   the run's agent-runner version, from STATE ('' when no run is up or an older run wrote none);
              F90: the TUI restarts and the run page reloads when it changes

F74 adds, outside the snapshot (read on demand, per session): `feed(name)` (its transcript as say/you/tool/out
entries); and the actions `chat_to` (any control session), `interrupt`, `new_control` and `quick_ask`; F86
`concept_chat` (a new control session about one concept).

Each action calls what the CLI already does, as a subprocess of the runner (`runner_cmd()`), so a page and a
terminal change the run exactly as a person typing the command would (B138: a Needs you button's `answer` runs
`plan confirm|change` or `sheet` itself); `chat`, a typed `answer` and a Chat or Do it here control open a new control session with the
message as its first (F176). Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess as sp
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

from agent_runner import need_detail
from agent_runner import plan as P
from agent_runner import plansync
from agent_runner import state as S
from agent_runner import theme
from agent_runner.config import runner_cmd

LOG_TAIL = 20  # run log lines a snapshot carries


# C44: the code is in files by area, each run in this module's own namespace in this order (the names are one
# module's, as before the split: a test's `ui_model.X = v` reaches all of it). Each has its test file:
# tests/test_ui_model.py (queue, snapshot), _release, _actions, _controls, _chat, _need; the settings' are in
# tests/test_config.py and test_web_settings.py. Put new code in the file of its area, not in this one.
PARTS = ('ui_model_queue', 'ui_model_snapshot', 'ui_model_actions', 'ui_model_controls', 'ui_model_chat', 'ui_model_need', 'ui_model_settings')


def _load_parts() -> None:
    for part in PARTS:
        path = Path(__file__).with_name(part + '.py')
        exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), globals())


_load_parts()
