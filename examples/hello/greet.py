"""Greet someone, in a language they know: `python3 greet.py Ada --lang fr`.

A deliberately small app. Each task in plan/TODO.md grows it a little.
"""
import argparse

from words import HELLO, word


def greet(name: str, lang: str = 'en') -> str:
    """The greeting for `name`; a blank name greets the world."""
    return f'{word(HELLO, lang)}, {name.strip() or "world"}!'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Greet someone.')
    parser.add_argument('name', nargs='?', default='')
    parser.add_argument('--lang', default='en', choices=sorted(HELLO))
    args = parser.parse_args(argv)
    print(greet(args.name, args.lang))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
