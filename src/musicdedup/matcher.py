"""Finds tracks with the same audio by comparing fingerprints of similar length."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from .fingerprint import Comparison, compare
from .scanner import Track

log = logging.getLogger(__name__)

WEAK_MAX_DURATION_DIFF = 0.5


def duration_tolerance(seconds: float) -> float:
    """Copies of the same audio differ in length only by encoder padding."""
    return max(1.5, 0.01 * seconds)


@dataclass
class Matches:
    # Track -> tracks with the same audio. Symmetric.
    same: dict[Track, dict[Track, Comparison]] = field(default_factory=lambda: defaultdict(dict))
    # Same recording but edited somewhere (e.g. explicit vs clean). Never treated as duplicates.
    variants: list[tuple[Track, Track, Comparison]] = field(default_factory=list)
    # Silence, very short tracks etc. of equal length: only used to complete an
    # album match, never as evidence on their own.
    weak: dict[Track, set[Track]] = field(default_factory=lambda: defaultdict(set))
    comparisons: int = 0

    def is_same(self, a: Track, b: Track) -> bool:
        return b in self.same.get(a, ())

    def is_weak(self, a: Track, b: Track) -> bool:
        return b in self.weak.get(a, ())


def find_matches(tracks: list[Track], progress: bool = False) -> Matches:
    usable = sorted((t for t in tracks if t.usable), key=lambda t: (t.duration, t.path))
    weak = {t: t.weak for t in usable}
    m = Matches()
    bar = None
    if progress:
        from tqdm import tqdm
        bar = tqdm(total=len(usable), unit='file', desc='Comparing')
    for i, a in enumerate(usable):
        limit = a.duration + duration_tolerance(a.duration)
        for b in usable[i + 1:]:
            if b.duration > limit:
                break
            if weak[a] or weak[b]:
                if weak[a] and weak[b] and b.duration - a.duration <= WEAK_MAX_DURATION_DIFF:
                    m.weak[a].add(b)
                    m.weak[b].add(a)
                continue
            m.comparisons += 1
            c = compare(a.fingerprint, b.fingerprint)
            if c is None:
                continue
            kind = c.kind
            if kind == 'same':
                m.same[a][b] = c
                m.same[b][a] = c
            elif kind == 'variant':
                m.variants.append((a, b, c))
        if bar:
            bar.update()
    if bar:
        bar.close()
    log.info("Compared %d pairs: %d tracks have a same-audio copy, %d edited-version pairs",
             m.comparisons, len(m.same), len(m.variants))
    return m
