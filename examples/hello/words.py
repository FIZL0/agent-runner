"""The words the app says, by language."""

HELLO = {'en': 'Hello', 'fr': 'Bonjour', 'de': 'Hallo'}


def word(words: dict[str, str], lang: str) -> str:
    """`words` in `lang`; an unknown language is a ValueError that names the ones there are."""
    if lang not in words:
        raise ValueError(f'no {lang!r} here, only {", ".join(sorted(words))}')
    return words[lang]
