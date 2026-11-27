# R21: removing the terminal UI

Research task, so no code changed here. Callers found:
- cli.py:217 `'ui': ('tui','main')` command table entry.
- cmds.py:739 opens tui main; cmds.py 1204-1480: launcher (`no_tui`, `launcher_keys` 't' key, `enter_words`, imports of PICK_RC, PICKER_ENV, refusal, window_title, TITLE_BACK from tui). Needs those helpers moved out first; Enter should open the web page, drop 'w' key.
- control.py:1195 `close_from_tui`.
- ui_model_controls.py / ui_model_need.py: a `tui` key field per action (keys used only by the terminal UI).
- theme.py docstring only; page/100-shared.js, page/189-lazy.js mention it.
- tests: test_cmds.py, test_need_blocked.py, test_needs_explained.py; tests/test_tui.py goes.
- docs/REFERENCE.md sections on the terminal UI.
