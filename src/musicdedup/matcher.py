"""Finds tracks with the same audio by comparing fingerprints of similar length."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

import numpy as np

from .fingerprint import _POP8_TABLE, FAST_PREFILTER_MAX_BER, Comparison, compare, prefilter_many
from .scanner import Track

log = logging.getLogger(__name__)

WEAK_MAX_DURATION_DIFF = 0.5

# Probes: a short 8-bit slice of every fingerprint, prepared once, so one track can be
# tested against all its candidates in a single numpy operation (they are neighbours in
# duration order, so their probes are contiguous rows). Unrelated tracks differ in ~50%
# of probe bits; anything under FAST_PREFILTER_MAX_BER goes on to the exact comparison.
PROBE_ITEMS = 128
PROBE_PAD = 16          # alignment search, in items, either side


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


class _Probes:
    def __init__(self, usable: list[Track]):
        n = len(usable)
        self.a = np.zeros((n, PROBE_ITEMS), dtype=np.uint8)
        self.b = np.zeros((n, PROBE_ITEMS + 2 * PROBE_PAD), dtype=np.uint8)
        self.ok = np.zeros(n, dtype=bool)
        for k, t in enumerate(usable):
            fp = t.fingerprint
            p = max(PROBE_PAD, len(fp) // 4)
            if p + PROBE_ITEMS + PROBE_PAD <= len(fp):
                self.a[k] = fp[p:p + PROBE_ITEMS]          # astype to uint8 keeps the low byte
                self.b[k] = fp[p - PROBE_PAD:p + PROBE_ITEMS + PROBE_PAD]
                self.ok[k] = True

    def passing(self, i: int, lo: int, hi: int) -> np.ndarray:
        """Which of tracks lo..hi-1 might match track i (both must have probes)."""
        win = np.lib.stride_tricks.sliding_window_view(self.b[lo:hi], PROBE_ITEMS, axis=1)
        bits = np.bitwise_count(win ^ self.a[i]) if hasattr(np, 'bitwise_count') else _POP8_TABLE[win ^ self.a[i]]
        bers = bits.sum(axis=2, dtype=np.int32).min(axis=1) / (8.0 * PROBE_ITEMS)
        return bers <= FAST_PREFILTER_MAX_BER


def _compare_range(usable: list[Track], weak: np.ndarray, durations: np.ndarray, probes: _Probes,
                   lo: int, hi: int, done: list[int], cancel) -> tuple[list, list, list, int]:
    """Compares tracks usable[lo:hi] with the tracks after them. Returns the pairs found
    rather than writing shared state, so ranges can run in parallel."""
    same, variants, weak_pairs = [], [], []
    comparisons = 0
    for i in range(lo, hi):
        a = usable[i]
        # Candidates are the tracks after this one in duration order, up to the tolerance.
        j = int(np.searchsorted(durations, a.duration + duration_tolerance(a.duration), side='right'))
        if j > i + 1:
            if weak[i]:
                for k in np.nonzero(weak[i + 1:j])[0]:
                    b = usable[i + 1 + k]
                    if b.duration - a.duration <= WEAK_MAX_DURATION_DIFF:
                        weak_pairs.append((a, b))
                maybe_idx = []
            else:
                strong = ~weak[i + 1:j]
                comparisons += int(strong.sum())
                if probes.ok[i]:
                    with_probe = strong & probes.ok[i + 1:j]
                    hit = np.zeros(j - i - 1, dtype=bool)
                    hit[with_probe] = probes.passing(i, i + 1, j)[with_probe]
                    # The rare tracks too short for a probe go through the per-pair test.
                    short = np.nonzero(strong & ~probes.ok[i + 1:j])[0]
                else:
                    hit = np.zeros(j - i - 1, dtype=bool)
                    short = np.nonzero(strong)[0]
                if len(short):
                    ok = prefilter_many(a.fingerprint, [usable[i + 1 + k].fingerprint for k in short])
                    hit[short[np.array(ok, dtype=bool)]] = True
                maybe_idx = np.nonzero(hit)[0]
        else:
            maybe_idx = []
        # The exact comparison decides, only for the few pairs that passed the probe test.
        for k in maybe_idx:
            b = usable[i + 1 + int(k)]
            damaged = bool((a.info and a.info.damaged) or (b.info and b.info.damaged))
            c = compare(a.fingerprint, b.fingerprint, allow_gap=damaged)
            if c is None:
                continue
            if c.kind == 'same':
                same.append((a, b, c))
            elif c.kind == 'variant':
                variants.append((a, b, c))
        done[0] += 1
        if cancel is not None and cancel.is_set():
            break
    return same, variants, weak_pairs, comparisons


def find_matches(tracks: list[Track], progress: bool = False, on_progress=None, cancel=None,
                 workers: int | None = None) -> Matches:
    usable = sorted((t for t in tracks if t.usable), key=lambda t: (t.duration, t.path))
    weak = np.array([t.weak for t in usable], dtype=bool)
    durations = np.array([t.duration for t in usable], dtype=np.float64)
    probes = _Probes(usable)
    m = Matches()
    n = len(usable)
    bar = None
    if progress:
        from tqdm import tqdm
        bar = tqdm(total=n, unit='file', desc='Comparing')
    # numpy releases the GIL in the heavy array work, so threads use several cores.
    workers = max(1, min(workers or os.cpu_count() or 1, 8))
    step = max(1, min(2000, n // (workers * 8) or 1))
    ranges = [(lo, min(n, lo + step)) for lo in range(0, n, step)]
    counters = [[0] for _ in ranges]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_compare_range, usable, weak, durations, probes, lo, hi, counters[k], cancel)
                   for k, (lo, hi) in enumerate(ranges)]
        reported = 0
        pending = set(futures)
        while pending:
            finished, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            done = sum(c[0] for c in counters)
            if on_progress:
                on_progress('comparing', done, n)
            if bar:
                bar.update(done - reported)
            reported = done
            if cancel is not None and cancel.is_set():
                for f in pending:
                    f.cancel()
                from .scanner import ScanCancelled
                raise ScanCancelled()
        for f in futures:   # in range order, so the result never depends on timing
            same, variants, weak_pairs, comparisons = f.result()
            m.comparisons += comparisons
            for a, b, c in same:
                m.same[a][b] = c
                m.same[b][a] = c
            m.variants.extend(variants)
            for a, b in weak_pairs:
                m.weak[a].add(b)
                m.weak[b].add(a)
    if bar:
        bar.close()
    log.info("Compared %d pairs: %d tracks have a same-audio copy, %d edited-version pairs",
             m.comparisons, len(m.same), len(m.variants))
    return m
