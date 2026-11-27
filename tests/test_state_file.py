"""F497: STATE gets written even while a reader blocks the rename (Windows)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_runner.state_file import put_in_place  # noqa: E402


def busy(*a):
    raise PermissionError('in use')


def main():
    d = Path(tempfile.mkdtemp())
    tmp, dest = d / 'STATE.tmp', d / 'STATE'
    dest.write_text('{"running": {}}')
    tmp.write_text('{"running": {"1": "B5"}}')
    assert put_in_place(tmp, dest, tries=2, pause=0, replace=busy)
    assert dest.read_text() == '{"running": {"1": "B5"}}' and not tmp.exists()
    n = [0]

    def flaky(a, b):
        n[0] += 1
        if n[0] < 3:
            raise PermissionError
        Path(a).replace(b)
    tmp.write_text('x')
    assert put_in_place(tmp, dest, tries=5, pause=0, replace=flaky) and dest.read_text() == 'x' and n[0] == 3
    print('ok')


if __name__ == '__main__':
    main()
