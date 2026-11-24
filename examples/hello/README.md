# hello: agent-runner's example project

A tiny greeting app and a plan for it, to try agent-runner on something that cannot hurt.

    python3 greet.py Ada --lang fr      # Bonjour, Ada!
    python3 -m unittest -q              # the gate

`agent-runner demo` made this copy, a git repo of its own whose "remote" is a folder on this machine. Nothing here
goes online, and no agent starts until you start a run. `agent-runner plan` shows the tasks: three can run side by
side, some wait for another (`after:`), one waits for your answer (Needs you), three are done.
