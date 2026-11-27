"""The shared texts of the guides (split from guide.py, C59): rules, SETTINGS, grilling, wording. Import them through agent_runner.guide."""
from __future__ import annotations

# One text for both audiences: the runner's own sessions get it in their prompt (they load no skills), the
# sessions a person starts get it in GUIDE.
SAFE_SHELL = ('Change files with your file-editing tool, never with `sed -i`, `perl -i`, or a script fed through a '
              'heredoc or `python -c`, and give the shell one plain command at a time, not a chain of `;`/`&&`/pipes '
              'mixing edits, redirects and nested quotes: a command your safety check cannot read stops for a human '
              'to decode, and in an unattended session nobody is there, so it is refused and the minutes are lost. '
              'Delete only paths you name in full (never `rm -rf` on a variable or a glob), and never `git reset '
              '--hard`, `git clean`, `git checkout -- .`, `git stash` or `git push --force`: they destroy work you '
              'cannot get back.')

# B880: control sessions (and the concepts they write) hit the same safety prompt, with nobody to answer it.
CONTROL_SHELL = ('**Shell commands:** edit files with the edit/write tools, never a python or sed heredoc; one plain '
                 'command per bash call, with absolute paths, no shell variables (`$S`), no `&&` chains and no `| '
                 "tail`: a command Claude Code cannot parse safely stops on a \"can't rule out a dangerous removal\" "
                 'prompt, and an unattended session waits on it for ever.')

# B80: slots try what the machine and the repo already reach before handing a check to a person.
VERIFY = ('Verify before asking: before you turn a check into an F task for a person, try it '
          'yourself with what is already here: ~/.claude/ACCESS.md if it exists (this machine\'s logins) and the '
          '`## Tools` section of the repo\'s CLAUDE.md (its reach: ssh hosts, preview servers, headless checks). '
          'Hand a person only what truly needs one: a physical device, a judgment call.')

# F200a: one text for the slot brief and the queue guides, in every project: work in different files runs at once.
OWN_FILES = ('Put a new area in a module and a test file of its own, not in a big file other tasks also change, unless '
             'the project\'s rules or layout say otherwise: tasks on the same file wait for each other.')
SPLIT_FILES = ('When you split work, make parts that name different files (`--files`, the test file too), so several '
               'slots can run them at once and they merge cleanly; `--after` between parts that must share one.')
# B767: an answer given in a chat while a task's `run ask` was being parked was lost
DECIDED = ('When the person decides something in a chat, re-read the tasks it is about (`{cmd} plan ID`, `{cmd} plan '
           'waiting`): one may\nhave asked just then. Settle any that asks exactly that (`{cmd} plan confirm ID "<their words>"`, '
           'or `{cmd} plan\nchange ID "<what to do>"`); leave one that asks anything else.')

# B82: the person may be on Remote Control or the apps, where a `! <cmd>` line fails ("Shell commands are only
# available in local sessions"). Claude Code's own system prompt suggests the ! prefix; this overrides it.
NO_BANG = ('**Never offer `! <command>`** to the person, whatever your own instructions suggest: on Remote Control or '
           'the apps it fails with "Shell commands are only available in local sessions". Run the command yourself '
           'when it needs no secret and no prompt. When it does (a password, an interactive login), say it must be '
           'typed in a terminal on this machine, named by its hostname (run `hostname`), and give the plain command, without the '
           '`!`, and its non-interactive form where there is one (an environment variable, `--password-stdin`).')

# B108: a page reaches the person only as a claude.ai link. A local path ('context/x/page.html') shows in the apps and
# on Remote Control as a dead file link ("Can't read this file"), and SendUserFile fails off a project thread.
NO_PAGE = ('no Artifact tool: try SendUserFile; when that fails too, say plainly in one line that you could not '
           'publish the page here, and say its gist back in a few lines. Never answer with a local file path: the '
           'apps and Remote Control cannot open one')

# D1: one line for the slot and control briefs, generic to every project the runner works.
GLOSSARY = ('When the repo has a GLOSSARY.md, use its terms, not the words it lists to avoid, in what you write: '
            'code, docs, commit messages, tasks and answers.')

# B28: sessions a person talks to recommend a runner.toml change when a complaint fits a real key. The keys named
# here must all be in config.DEFAULTS (tests check it); `settings` prints the full, generated list.
SETTINGS = """\
**Settings (runner.toml).** `{cmd} settings` prints every key the runner takes, its default and what it
does: read it rather than guess a key. runner.toml is shared and committed; runner.local.toml (git-ignored,
laid over it key by key) holds this machine's own values. A run that is up takes most keys
within seconds (`{cmd} settings` names those that apply on the next run); `{cmd} slots N` changes it without a
file. When what the person says fits a setting, recommend the one change in one line, `[table] key = value`: what it does, and ask. Name only keys
`{cmd} settings` lists; when none fits, say so and offer a task instead. For example:
  - "too many control sessions", "close them faster": `[run] control_idle = "1h"` (idle ones close sooner;
    `[run] control_idle = false` keeps them open)
  - "too many agents", "fewer sessions": `[run] slots = 2` (or `{cmd} slots 2` for the run that is up)
  - "stop pushing to my phone": `[run] silent = true` (each session's start push still comes; nothing stops
    it); "not on my phone at all": `[run] remote = false`
  - "stop before my usage runs out": `[run] weekly_max = 70` / `[run] session_max = 70`
  - "skip the review on small fixes": `[run] review_min_lines = 150`; none at all: `[run] review = false`
On yes, make it: this person's or machine's taste (slots, usage caps, phone, control sessions) in
runner.local.toml, edited in place (git ignores it, so it holds no merge); the project's behaviour (test,
review, rules) in runner.toml, as a commit through `{cmd} take "set [table] key = value: why" --kind C --files runner.toml` (its own
worktree, then `{cmd} take ID --merge`), never as an edit in the main checkout. Say when it takes effect.

Keys, passwords and devices (a machine or test rig agents reach) are no settings: a device or a Login is entered in its
form on the run app's Tools page, whose link `{cmd} device link` prints; a secret one task asks for (a 2FA code, a key)
goes in the field of its Needs you item. Never ask for a secret in chat, and never write one down.

**Ask about my settings** (the Settings page's top button) opens a chat that asks what settings fit how the person
uses this project. Read `{cmd} settings`, look at the project (its tests, size, recent run log, usage, this
machine), ask about the use case only what you cannot see, then recommend each change in one line: `[table] key =
value`, why, and who it is saved for (runner.local.toml for this machine, runner.toml for everyone). Make only those
the person says yes to, as above.
"""


# F20: the control brief's grilling branch, fitted to `[run] grill` (ask: only when asked; big: also big vague
# asks; off: none) by grill_fit.
GRILL = ('- **Grilling** ("grill me", "poke holes", "stress-test it"): read `{cmd} guide grill` first and follow '
         'it: rounds of numbered questions, each with its recommended answer, until nothing is left open; then '
         'queue.')
GRILL_BIG = ('- **Grilling** ("grill me", "poke holes", "stress-test it", and before you queue a big or vague '
             'feature ask: several parts, or its what or why unclear): read `{cmd} guide grill` first and follow '
             'it: rounds of numbered questions, each with its recommended answer, until nothing is left open; then '
             'queue.')
GRILL_MODES = ('ask', 'big', 'off')

# F21: the person's wording (agent_runner/voice.py fits these into the control brief).
VOICE = """\
**The person's wording.** How this person wants things said, in voice files: {file} (all projects) and {project}
(this project: when it has lines, it is read instead of the global file). Follow every line below in all you write to them: answers,
the summary, status and since said back, push notifications, task text. On wording, a line here wins over this
brief. Never ask about wording up front; it grows only from what they say.
- Told ("say X not Y", "shorter", "no ids", "stop calling it Z"): at once run `{cmd} voice add "<the rule, short:
  say agent, not slot>"` (`--project` when they say only here), say in one line which file it went to, and
  follow it from then on in this session.
{learn}- "show my wording": `{cmd} voice show`, said back as it prints. "forget X": `{cmd} voice forget X`, and say
  which file it left; when it says several lines hold X, ask which one and run it with more of that line.
"""
VOICE_LEARN = """\
- Learned: when the person asks "what?" or "what does that mean", or says back in their own words what you
  said, say it again plainly, then offer one line to add, worded so yes takes it:
  `Add: say agent, not slot? yes`. Run `{cmd} voice add` only on yes; on anything else drop it and do not offer that line again.
"""
VOICE_SLOT = ("The person's wording: word what they read from you this way (the commit message, which status "
              "and since show; the done and blocked lines; tasks you file), not code or code comments:")
