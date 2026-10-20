"""`python -m agent_runner`: the same CLI as `./run` and `agent-runner` (how an installed runner calls
itself from a hook)."""
import sys

from agent_runner.cli import main

sys.exit(main())
