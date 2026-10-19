"""Prepare downloads from stored source without exposing server paths."""
from io import BytesIO
import os
from pathlib import Path
from tempfile import SpooledTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED

from werkzeug.utils import secure_filename


def build_bot_download(bot, version, upload_root):
    """Return (open binary stream, download name, MIME type); caller closes it.

    Authorization belongs to the route and must happen before calling here.
    ZIP uploads are stored as extracted src/ trees, so exports are rebuilt.
    """
    extension = '.py' if bot['language'] == 'python3' else '.cpp'
    name = f"{secure_filename(bot['bot_name']) or 'bot'}-v{version['version_number']}"
    if version['source_code'] is not None:
        return BytesIO(version['source_code'].encode('utf-8')), name + extension, 'text/plain'

    root = Path(upload_root).resolve()
    bot_root = root / str(bot['user_id']) / str(bot['id'])
    if (bot_root.resolve() != bot_root.absolute() or not bot_root.resolve().is_relative_to(root)
            or not version['file_path']):
        raise FileNotFoundError('Download unavailable')
    workdir = Path(version['file_path']).resolve()
    if not workdir.is_relative_to(bot_root.resolve()) or not workdir.exists():
        raise FileNotFoundError('Download unavailable')

    def is_link(path):
        return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())

    if workdir.is_file():
        if workdir.suffix.lower() not in ('.py', '.cpp', '.cc'):
            raise FileNotFoundError('Download unavailable')
        return workdir.open('rb'), name + workdir.suffix.lower(), 'text/plain'

    # Canonical single-file uploads live in vN/; ZIP trees live in vN/src/.
    entry = workdir / ('main.py' if bot['language'] == 'python3' else 'main.cpp')
    if workdir.name != 'src' and entry.is_file() and not is_link(entry):
        return entry.open('rb'), name + extension, 'text/plain'

    archive = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
    try:
        count = 0
        with ZipFile(archive, 'w', compression=ZIP_DEFLATED) as output:
            for directory, dirs, files in os.walk(workdir, followlinks=False):
                parent = Path(directory)
                dirs[:] = sorted(d for d in dirs if d != '__pycache__' and not is_link(parent / d))
                for filename in sorted(files):
                    path = parent / filename
                    if is_link(path) or not path.is_file() or path.suffix in ('.pyc', '.pyo'):
                        continue
                    if not path.resolve().is_relative_to(workdir):
                        raise FileNotFoundError('Download unavailable')
                    output.write(path, path.relative_to(workdir).as_posix())
                    count += 1
        if not count:
            raise FileNotFoundError('Download unavailable')
        archive.seek(0)
        return archive, name + '.zip', 'application/zip'
    except Exception:
        archive.close()
        raise
