"""Finding album artwork: a picture file in the folder, else one embedded in a track."""

from __future__ import annotations

import os

COVER_NAMES = ('cover', 'folder', 'front', 'album', 'albumart')
IMAGE_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}


def find_cover_file(folder: str) -> str | None:
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    images = [n for n in names if os.path.splitext(n)[1].lower() in IMAGE_TYPES and not n.startswith('._')]
    for stem in COVER_NAMES:
        for n in sorted(images):
            if os.path.splitext(n)[0].lower() == stem:
                return os.path.join(folder, n)
    return os.path.join(folder, sorted(images)[0]) if images else None


def embedded_cover(path: str) -> tuple[bytes, str] | None:
    """Returns (image bytes, mime type) from a track's tags, if it has a picture."""
    try:
        from mutagen import File
        audio = File(path)
    except Exception:
        return None
    if audio is None:
        return None
    pictures = getattr(audio, 'pictures', None)          # FLAC
    if pictures:
        return pictures[0].data, pictures[0].mime or 'image/jpeg'
    tags = getattr(audio, 'tags', None)
    if tags is None:
        return None
    for key in getattr(tags, 'keys', lambda: [])():
        if str(key).startswith('APIC'):                  # ID3
            frame = tags[key]
            return frame.data, frame.mime or 'image/jpeg'
    covr = tags.get('covr') if hasattr(tags, 'get') else None   # MP4
    if covr:
        img = covr[0]
        return bytes(img), 'image/png' if getattr(img, 'imageformat', 0) == 14 else 'image/jpeg'
    return None
