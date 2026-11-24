"""C45: the run page's web.py, attachments kept under the notes dir.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""


UPLOAD_BYTES = 50 * 1024 * 1024  # the largest attachment the page may upload


def upload_dir() -> Path:
    """F79: where attachments are kept: <notes>/uploads (.runner/uploads by default), git-ignored with it."""
    d = S.C.notes('uploads', 'x').parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    """An uploaded file's name made safe to keep: its last path part, only letters, digits and . _ - (others
    become _), no leading dot, at most 100 characters; 'file' when nothing is left."""
    base = re.split(r'[\\/]', name or '')[-1]
    base = re.sub(r'[^A-Za-z0-9._-]+', '_', base).lstrip('.')[-100:]
    return base or 'file'


def save_upload(name: str, data: bytes) -> dict:
    """F79: keep an attachment under `upload_dir()` as <time>-<safe name> (never over another file): {'ok', 'path'
    (absolute, for the session it is handed to), 'name'}."""
    d = upload_dir()
    stem = time.strftime('%Y%m%d-%H%M%S') + '-' + safe_name(name)
    p, n = d / stem, 1
    while p.exists():
        n += 1
        p = d / f'{n}-{stem}'
    p.write_bytes(data)
    return {'ok': True, 'path': str(p.resolve()), 'name': p.name}


