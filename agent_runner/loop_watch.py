"""The run's watches of CI and issues."""

import datetime as dt
import json
import os
import re
import shutil
import signal
import sys
import threading
import time
import traceback
import webbrowser
from contextlib import ExitStack
from pathlib import Path

from agent_runner import agent_hold, brief_arrives, claude_use, exit_hook, fallback as FB, settings_live, ci, file_split, gitops, no_commits, no_push, plan as P, plansync, plat, shared_tools, stack, undo
from agent_runner.config import claude_model, RUNNER, ensure_local, finished_mark, shown_cmd
from agent_runner.done import TESTED
from agent_runner.gitops import missing_remote, push
from agent_runner.state import (alarm, ask_stop, C, clean, clear_stop, commit_plan, default_branch, FORCED, forced,
    git, HIDDEN, IDLE, init, KEYS, KEYS_LOCK, LANDING, log, MERGE, note, PAUSED, plan_rel, plan_text, POWER, queued,
    READING, ROOT, share, SLOTS_DIR, stop_note, STOP_SAID, stopped_by, stopping, WAKE, EV_DEFERRED, EV_DROPPED, EV_IDLE, EV_LEFT, EV_NO_COMMITS, EV_PARKED, EV_RUN_UP,
    EV_STALLED, EV_STOP_ASKED, EV_STOP_BACK, EV_STOPPED, EV_CONTEXT)
from agent_runner.autorelease import auto_release, auto_release_of, AUTO_RELEASE_SEEN, landed_since_release
from agent_runner.brief import no_remote_line
from agent_runner.sched import agent_held, blocked_by_edits, forgive_park, keep_claims, note_committed, PARK_LIMIT, parked_attempts, pick, splitting, tasks
from agent_runner.tools import take_end
from agent_runner.login import retry_held, unlogged
from agent_runner.asks import block_asks, EV_FINISHED, no_slot, park_asked, unblocked_asks
from agent_runner.slots import (adopt, backend, DISK_AT, DISK_SAID, du, free_branch,
    free_gb, GB, hidden_line, HiddenMux, MUX, remote_any, remote_line, REMOTE_URL, resume, save_leftovers,
    single_run, slot_env, slot_shim, SLOTS, start, transcript, trim, unmerged, budget_mark, budgets, SPENT)
from agent_runner.teardown import close_page, end_own, PAGE, RUN_LOCK, wait_last_run
from agent_runner.watch import (_account, api_down, auto_upgrade, code_start, context_over, cut_off, drop_session_tmp,
    end_orphans, memory_watch, queue_cut_off, queue_resume, ask_restart, restart_if_upgraded, resumes, RESUMES_MAX, stalled,
    START_TRIES, state_line, stats, stop_hook, stop_waiter, sweep_tmp, update_watch, upgrade, usage_pct, watch_code, weekly)
from agent_runner.join import EDITED, EDITS_POLL, ELSEWHERE, REMIND_EVERY, TASK_SID, WAITING
from agent_runner.land import drop_wips, idle_line, prune_wips, reopen_landed, REOPENED, retry_reopened, wip_main, no_gate_line
from agent_runner.merge import (AHEAD_BUSY, AHEADS, before_start_fails, FIX_DIRS, FIX_DIRS_LOCK, FIXED, gate_runs,
    HELD, last_words, left_merging, merge)
from agent_runner.control import hand_hook, rc_sweep_start, start_control, start_control_server
from agent_runner.feed import rc_sweep_stop



def ci_flows(branch: str) -> tuple[list[str], str]:
    """`[run] ci_watch` as (workflow files, event their runs must come from): "auto" (the default) is every
    workflow that runs on a push to `branch`, push runs only; a name or list is just those, any event;
    false, [] or "" is none."""
    w = C.run['ci_watch']
    if w == 'auto':
        return ci.push_workflows(ROOT, branch), 'push'
    if not w:
        return [], ''
    return ([w] if isinstance(w, str) else list(w)), ''


CI_UNSEEN: list[str] = []  # why gh could not see the repository, once it has been said
CI_RERUN = True  # a red run's failed jobs run once more before a task is filed: GitHub's own outages read red too
CI_AT = [0.0]  # when `watch_ci` last asked GitHub


def watch_ci(branch: str, force: bool = False) -> list[str]:
    """`[run] ci_watch`: file one critical task for a red workflow run on the shared branch, or put the run on the task
    that has its failing test (see `ci`, `ci.file_red`).

    Every `ci.CI_POLL` s from the run loop, and only when MERGE is free: the task is committed in the main
    checkout like `reopen_landed`'s, and a loop that waited out a gate here would start nothing for an hour.
    Left alone, as there, while TODO.md has edits nobody committed. The ids filed.
    """
    if not force and time.time() - CI_AT[0] < ci.CI_POLL:
        return []
    flows, event = ci_flows(branch)
    if not flows:
        return []
    if not MERGE.acquire(blocking=False):
        return []
    filed: list[str] = []
    hold = ExitStack()
    try:
        CI_AT[0] = time.time()
        if C.plan_external:  # the whole look: a gh call or two, seconds
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if git('branch', '--show-current').stdout.strip() != branch or \
                git('status', '--porcelain', '--', plan_rel('')).stdout.strip():
            return []
        gh = ci.gh_in(ROOT)
        if why := ci.reachable(gh):
            if not CI_UNSEEN:
                CI_UNSEEN.append(why)
                log(f'! ci_watch: gh cannot see this repository ({why}); CI on {branch} is not watched until it '
                    f'can (`gh auth status`; `ci_watch = false` in [run] to stop looking)')
            return []
        CI_UNSEEN.clear()
        for wf in flows:
            ls = P.lines(ROOT / rel)
            open_text = '\n'.join(l for l in ls if (m := P.ITEM.match(l)) and m.group(2) != 'x')
            seen = ci.seen_file(C.notes, wf)
            was = seen.read_text() if seen.exists() else ''
            if not (got := ci.to_file(gh, wf, branch, seen, open_text, event, CI_RERUN, log)):
                continue
            todo, done = ROOT / rel, ROOT / plan_rel('DONE.md')
            put = ci.file_red(got, todo, done, git)
            if not put:
                continue
            rels = [plan_rel(os.path.relpath(p, C.plan_dir)) for p in put.paths]
            own = rels[-1]
            git('add', '--', own)
            mark = ci.marker(wf, branch)
            if not commit_plan(f'Plan: {put.tid}, {mark}', *rels):
                git('reset', '-q', '--', own)
                for r in rels:
                    if git('checkout', '-q', '--', r).returncode:
                        (ROOT / r).unlink(missing_ok=True)  # a long form that was not there before
                seen.write_text(was)  # not filed: the next look tries that run again
                continue
            filed.append(put.tid)
            if put.how.startswith('reopened'):
                REOPENED.add(put.tid)  # a new attempt, though this run tried it before
            note(f'{put.tid}: {put.how}, {mark}')
            log(f'{put.tid}: {put.how}, {mark}: {got.text[:200]}')
    finally:
        hold.close()
        MERGE.release()
    return filed


ISSUES_UNSEEN: list[str] = []  # why gh could not see the repository's issues, once it has been said
ISSUES_AT = [0.0]  # when `watch_issues` last asked GitHub


def watch_issues(branch: str, force: bool = False) -> list[str]:
    """`[run] issues_watch`: file one task per new open GitHub issue, and answer the issues whose task closed
    (see `issues`). On the `ci_watch` cadence and only when MERGE is free, committed in the main checkout as
    `watch_ci` commits its tasks. The ids filed."""
    from agent_runner import issues as I
    labels = I.labels_of(C.run.get('issues_watch', False))
    if labels is None or (not force and time.time() - ISSUES_AT[0] < ci.CI_POLL):
        return []
    if not MERGE.acquire(blocking=False):
        return []
    filed: list[str] = []
    hold = ExitStack()
    try:
        ISSUES_AT[0] = time.time()
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if git('branch', '--show-current').stdout.strip() != branch or \
                git('status', '--porcelain', '--', plan_rel('')).stdout.strip():
            return []
        gh = ci.gh_in(ROOT)
        if why := ci.reachable(gh):
            if not ISSUES_UNSEEN:
                ISSUES_UNSEEN.append(why)
                log(f'! issues_watch: gh cannot see this repository ({why}); its issues are not read until it '
                    f'can (`gh auth status`; `issues_watch = false` in [run] to stop looking)')
            return []
        ISSUES_UNSEEN.clear()
        seen_f, filed_f = C.notes('issues.seen'), C.notes('issues.filed')
        book = I.read_filed(filed_f)
        # the issues whose task has closed: a comment naming the merge commit; closed too under trust
        plan_lines = [*P.lines(ROOT / rel), *P.lines(ROOT / plan_rel('DONE.md'))]

        def commit_of(tid: str) -> str:
            # the merge's own commit (merge.py's message); a task's commits alone could be any id's prefix
            return git('log', '-1', '--format=%h', '-F', f"--grep=Merge branch 'task/{tid}'", branch).stdout.strip()
        for tid, n, trust, sha, line in I.to_answer(book, plan_lines, commit_of):
            if I.answer(gh, n, tid, trust, sha, line):
                book.pop(tid, None)
                I.write_filed(filed_f, book)
                log(f'{tid}: {"closed" if trust == "trust" else "commented on"} {I.marker(n)}'
                    + (f' (landed in {sha})' if sha else ' (no code change)'))
        got = I.open_issues(gh, labels)
        if got is None:
            return []
        seen = I.read_seen(seen_f)
        trust = I.trust_of(C.run.get('issues_trust', 'skeptical'))
        me = I.owner(gh) if trust == 'skeptical' and any(i['number'] not in seen for i in got) else ''
        for issue in got:
            n = issue['number']
            if n in seen:
                continue
            ls = P.lines(ROOT / rel)
            open_text = '\n'.join(l for l in ls if (m := P.ITEM.match(l)) and m.group(2) != 'x')
            if I.named(issue, open_text):
                seen.add(n)
                I.write_seen(seen_f, seen)
                continue
            how = 'trust' if me and (issue.get('author') or {}).get('login') == me else trust
            text, long = I.task(issue, how)
            tid = P.add(I.kind_of(issue), text, todo=ROOT / rel, pri='normal')
            own = plan_rel(f'{P.TASKS}/{tid}.md')
            (ROOT / own).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / own).write_text('\n'.join([f'# {tid} — {I.marker(n)}', '', *long, '']), encoding='utf-8')
            git('add', '--', own)
            if not commit_plan(f'Plan: {tid}, {I.marker(n)}', rel, own):
                git('reset', '-q', '--', own)
                git('checkout', '-q', '--', rel)
                (ROOT / own).unlink(missing_ok=True)
                continue  # not filed: the next look tries it again
            seen.add(n)
            I.write_seen(seen_f, seen)
            book[tid] = {'number': n, 'trust': how}
            I.write_filed(filed_f, book)
            filed.append(tid)
            note(f'{tid}: filed ({how}), {I.marker(n)}')
            log(f'{tid}: filed ({how}), {I.marker(n)}: {text[:200]}')
    finally:
        hold.close()
        MERGE.release()
    return filed
