"""Understanding releases: which album and edition a folder holds.

Used to keep releases intact. A standard album whose tracks all appear on the
deluxe edition is still its own release, so it is only removed if asked; a copy
of the same edition with tracks missing is just an incomplete copy.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass

# Words that mark a distinct edition or version of a release.
_EDITION_PATTERNS = {
    'deluxe': r'deluxe',
    'expanded': r'expanded',
    'extended': r'extended',
    'special': r'special',
    'limited': r'limited',
    'collector': r"collector'?s?",
    'anniversary': r'anniversary',
    'remaster': r're-?master(?:ed)?',
    'reissue': r're-?issue',
    'bonus': r'bonus',
    'live': r'live',
    'unplugged': r'unplugged',
    'acoustic': r'acoustic',
    'demo': r'demos?',
    'instrumental': r'instrumentals?',
    'mixed': r'(?:dj[ -])?mixed',
    'remix': r'remix(?:es|ed)?',
    'box set': r'box(?:ed)?[ -]?set',
    'complete': r'complete',
    'mono': r'mono',
    'tour': r'tour edition',
    'japan': r'japan(?:ese)?',
}
_EDITION_RE = {k: re.compile(rf'\b{v}\b', re.I) for k, v in _EDITION_PATTERNS.items()}
_DISC_FOLDER_RE = re.compile(r'^\s*(?:cd|disc|disk|side)\s*[-_]?\s*\w{1,3}\s*$', re.I)
_BRACKETS_RE = re.compile(r'[(\[{][^)\]}]*[)\]}]')
_NOISE_RE = re.compile(r'\b(?:edition|version|explicit|clean|e|\d{4})\b', re.I)
_COPY_NAME_RE = re.compile(r'(?:\bcopy(?:\s*\d+)?|\(\d+\))\s*$', re.I)


def _norm(text: str) -> str:
    text = text.lower().replace('&', ' and ')
    return re.sub(r'[^0-9a-z]+', ' ', text).strip()


def edition_markers(text: str) -> frozenset[str]:
    return frozenset(k for k, rx in _EDITION_RE.items() if rx.search(text))


def base_title(text: str) -> str:
    """Album title without edition words, years, explicit markers or brackets."""
    t = _BRACKETS_RE.sub(' ', text)
    for rx in _EDITION_RE.values():
        t = rx.sub(' ', t)
    t = _NOISE_RE.sub(' ', t)
    return _norm(t)


def is_disc_folder(name: str) -> bool:
    return bool(_DISC_FOLDER_RE.match(name))


@dataclass(frozen=True)
class Release:
    title: str                 # normalised base title
    editions: frozenset[str]   # e.g. {'deluxe'}

    def describe(self) -> str:
        return ', '.join(sorted(self.editions)) or 'standard'


def release_of(folder_path: str, album_tags: list[str]) -> Release:
    """Works out the release from the most common album tag, plus the folder name
    (and the parent's, for disc folders like 'CD 1')."""
    name = os.path.basename(folder_path)
    names = [name]
    if is_disc_folder(name):
        names = [os.path.basename(os.path.dirname(folder_path))]
    tags = [a for a in album_tags if a.strip()]
    album = Counter(tags).most_common(1)[0][0] if tags else names[0]
    markers = edition_markers(album) | edition_markers(' '.join(names))
    return Release(title=base_title(album) or base_title(names[0]), editions=markers)


def same_edition(a: Release, b: Release) -> bool:
    return a.title == b.title and a.editions == b.editions


def accidental_copy(keep_name: str, keep_track: int, keep_disc: int,
                    other_name: str, other_track: int, other_disc: int) -> bool:
    """Is a same-audio file in the same folder an accidental copy rather than a
    track the release repeats on purpose (a reprise, a bonus repeat)?"""
    keep_stem, keep_ext = os.path.splitext(keep_name)
    other_stem, other_ext = os.path.splitext(other_name)
    if keep_ext.lower() != other_ext.lower():
        return True                         # the same track in two formats
    if _COPY_NAME_RE.search(other_stem) and not _COPY_NAME_RE.search(keep_stem):
        return True                         # "Song (1).flac", "Song copy.flac"
    if keep_track and other_track:
        return (keep_track, keep_disc) == (other_track, other_disc)
    return False                            # no evidence: keep both
