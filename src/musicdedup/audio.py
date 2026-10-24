"""Audio file types and quality information."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

# Everything fpcalc (via FFmpeg) can usually decode. Any file with one of these
# extensions is treated as audio: if it can't be fingerprinted, its folder is
# never removed, because we can't tell whether it holds unique music.
AUDIO_EXTENSIONS = frozenset({
    '.aac', '.ac3', '.aif', '.aifc', '.aiff', '.alac', '.ape', '.dff', '.dsf', '.dts',
    '.flac', '.m4a', '.m4b', '.mka', '.mp2', '.mp3', '.mpc', '.oga', '.ogg', '.opus',
    '.tta', '.wav', '.wma', '.wv',
})

LOSSLESS_EXTENSIONS = frozenset({
    '.aif', '.aifc', '.aiff', '.alac', '.ape', '.dff', '.dsf', '.flac', '.tta', '.wav', '.wv',
})


def is_audio(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS


@dataclass(frozen=True)
class AudioInfo:
    """Format details used to decide which copy of a track is better."""

    lossless: bool
    bits: int = 0           # bits per sample (lossless only)
    sample_rate: int = 0
    bitrate: int = 0        # bits per second
    channels: int = 0
    artist: str = ''
    album: str = ''
    title: str = ''
    track: int = 0
    disc: int = 0
    damaged: bool = False   # decodable only by skipping bad frames (a glitch somewhere)

    def quality(self) -> tuple:
        """Sortable format quality: higher is better. Lossless beats lossy, then
        resolution, then bitrate. File size is deliberately not part of it: copies
        that differ only in tags differ by a few bytes."""
        # A damaged copy ranks below a clean one of the same kind, but a damaged lossless
        # copy still beats any lossy one: one glitch isn't worth trading lossless away for.
        clean = int(not self.damaged)
        if self.lossless:
            return (1, clean, self.bits or 16, self.sample_rate, self.channels, 0)
        return (0, clean, 0, 0, self.channels, self.bitrate)

    def describe(self) -> str:
        damaged = ' (damaged)' if self.damaged else ''
        if self.lossless:
            return f"lossless {self.bits or '?'}-bit/{self.sample_rate / 1000:g}kHz{damaged}"
        return f"lossy {round(self.bitrate / 1000)}kbps{damaged}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> AudioInfo:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def _first_tag(tags, key: str) -> str:
    try:
        value = tags.get(key) if tags is not None else None
    except Exception:
        return ''
    if isinstance(value, list):
        value = value[0] if value else ''
    return str(value or '')


def _number(text: str) -> int:
    """'3', '03/12' -> 3; anything else -> 0."""
    head = text.split('/')[0].strip()
    return int(head) if head.isdigit() else 0


def read_audio_info(path: str) -> AudioInfo:
    """Reads format and tags with mutagen. Never raises: unreadable tags only
    reduce how much we know about quality."""
    ext = os.path.splitext(path)[1].lower()
    lossless = ext in LOSSLESS_EXTENSIONS
    try:
        from mutagen import File
        audio = File(path, easy=True)
    except Exception as e:
        log.debug("Could not read tags from %s: %s", path, e)
        return AudioInfo(lossless=lossless)
    if audio is None:
        return AudioInfo(lossless=lossless)

    info = audio.info
    codec = str(getattr(info, 'codec', '') or '').lower()
    if ext in ('.m4a', '.m4b'):
        lossless = codec == 'alac'
    return AudioInfo(
        lossless=lossless,
        bits=int(getattr(info, 'bits_per_sample', 0) or 0) if lossless else 0,
        sample_rate=int(getattr(info, 'sample_rate', 0) or 0),
        bitrate=int(getattr(info, 'bitrate', 0) or 0),
        channels=int(getattr(info, 'channels', 0) or 0),
        artist=_first_tag(audio.tags, 'artist'),
        album=_first_tag(audio.tags, 'album'),
        title=_first_tag(audio.tags, 'title'),
        track=_number(_first_tag(audio.tags, 'tracknumber')),
        disc=_number(_first_tag(audio.tags, 'discnumber')),
    )
