#!/usr/bin/env python3
"""tools/outline.py: the outline of one file of each kind.

    python3 tests/test_outline.py          (no network, no agent, under a second)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from _check import check, report

TOOL = Path(__file__).resolve().parent.parent / 'tools/outline.py'

PY = '''"""Words.
# --- not a section ---
"""
import os

# --- the first part ---------
def one(a):
    def inner():
        pass

@decorated
class Box:
    size = 1
    async def open(self):
        pass

if os.name:
    def under_if():
        pass
'''
JS = '''import x from 'x';
/*
function commented(){}
*/
// --- the page ---
export async function load(a){
  function inner(){}
  if(a){
  }
}
const pick=(a,b=f(1))=>a+b;
const plain=3;
let one = async x => x;
export default class Box extends Base {
  #n = 1;
  constructor(a) {
    if (a) {
    }
    each(function(){
    })
  }
  static async open(){
  }
}
function* after(){}
const wide=(
  a,
  b)=>{
}
class Two {
  far(a,
    b) {
  }
}
'''
MD = '''# Title

## Part one ##

```sh
# not a heading
```

~~~~
## nor this
~~~
# nor this
~~~~
###no space
### Part two
'''


def out(name: str, text: str):
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / name
        f.write_text(text, encoding='utf-8')
        return subprocess.run([sys.executable, str(TOOL), str(f)], capture_output=True, text=True)


def same(name: str, text: str, want: list[str], what: str):
    r = out(name, text)
    check(r.returncode == 0 and r.stdout.strip('\n').splitlines() == want, what, r.stdout + r.stderr)


def test_kinds():
    print('outline: one file of each kind')
    same('a.py', PY, ['6 --- the first part', '7 def one', '12 class Box', '14   def open', '18 def under_if'],
         'Python: sections, functions, classes and methods; not nested ones, not in a string')
    same('a.py', 'class A:\n    def b(self):\n<<<<<<< HEAD\n', ['1 class A', '2   def b'],
         'Python that does not parse is read by its lines')
    js = ['5 --- the page', '6 function load', '11 function pick', '13 function one', '14 class Box',
          '16   constructor', '22   open', '25 function after',
          '26 function wide', '30 class Two', '31   far']
    same('a.js', JS, js, 'JavaScript: sections, functions, classes and methods; not nested ones or comments')
    same('a.mjs', JS, js, 'and .mjs the same')
    same('a.md', MD, ['1 # Title', '3 ## Part one', '15 ### Part two'], 'Markdown: headings; not in code')


def test_rest():
    print('outline: other files')
    same('a.css', 'a{}\n', [], 'another kind prints nothing')
    same('a.md', '# ' + 'x' * 200, ['1 # ' + 'x' * 78], 'a long line is cut')
    r = subprocess.run([sys.executable, str(TOOL), '/nonexistent/a.py'], capture_output=True, text=True)
    check(r.returncode == 1 and 'Traceback' not in r.stderr, 'a file that is not there says so', r.stderr)


if __name__ == '__main__':
    sys.exit(report([test_kinds, test_rest]))
