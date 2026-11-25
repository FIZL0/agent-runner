# agent-runner: rules for agents

Python 3, standard library only (no dependencies). Run it as `./run`.

## Where things are

- `agent_runner/` the package; one module per area, most small. By area:
  - `cli.py`, `cmds.py`, `__main__.py`: commands and their dispatch
  - `config.py`: every setting and its default (runner.toml, user config)
  - `loop*.py`, `sched.py`, `slots.py`, `runner.py`: the run loop, picking, slots
  - `done.py`, `merge.py`, `land.py`, `join.py`, `gitops.py`: finishing a task, merging, publishing
  - `plan*.py`, `brief*.py`, `plansync.py`: the task list and the brief a session gets
  - `control*.py`: control sessions; `asks.py`, `need_detail.py`, `sheet.py`: Needs you
  - `ui_model*.py`: the one snapshot every view draws; `tui.py` terminal UI
  - `web*.py`, `home*.py`: the run app and Runner Home (server side)
  - `page/`: the run app's page parts, CSS and JS named `NNN-<area>.<ext>`, joined by number order
  - `web_page.html`: the page's shell
- `tests/test_*.py` one suite per area; helpers in `tests/_check.py` (and `tests/_web.py` for the page)
- `tools/` scripts the repo's own config uses; `docs/` the documents below

## Tests

Run one suite: `python3 tests/test_<area>.py` (no framework, plain prints, exit 1 on failure).
The gate runs all of them in turn. New area: a module and a test file of its own.

## Style

- Page work: read `docs/STYLE.md` first; a new rule goes there in the same commit.
- Use GLOSSARY.md's terms in code, docs, commits and tasks, not the words it says to avoid.
- Keep changes local: don't move, rename or reformat code you did not come for.
- Every task adds a line under Unreleased in `CHANGELOG.md` ("Added/Changed/Fixed: … (ID)").

## Docs

`docs/REFERENCE.md` is long: find a section with `grep -n '^#' docs/REFERENCE.md`, read just that range, never the whole.
Others: `docs/SETUP.md`, `docs/FACTORY.md`. The README is for people.

Tasks: this repo is worked by agent-runner. Use the agent-runner skill (or run `agent-runner guide`): queue work with `agent-runner plan add`, never edit the plan's TODO.md by hand, never merge task/* or wip/* branches. Asked to do something now? Use `agent-runner take "what" --kind K` (a worktree of your own; `--here` brings edits already made along); never edit the main checkout.
