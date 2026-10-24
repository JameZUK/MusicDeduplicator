"""Chromaprint fingerprints: generating them with fpcalc and comparing them locally.

A raw Chromaprint fingerprint is a sequence of 32-bit values, one per ~0.124 s
of audio. Two encodings of the same audio produce nearly identical sequences;
different songs differ in about half their bits. Comparing locally (rather than
asking AcoustID which recording a file is) lets us tell apart cases AcoustID
merges, such as explicit and clean edits of the same recording.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

import numpy as np

ITEM_SECONDS = 4096 / 3 / 11025   # duration covered by one fingerprint value
BLOCK_ITEMS = 20                  # ~2.5 s windows for spotting local edits
MAX_OFFSET = 10                   # alignment search, in items (~1.2 s)
PREFILTER_ITEMS = 160             # ~20 s window used to reject non-matches cheaply
PREFILTER_MAX_BER = 0.30
MIN_ITEMS = 40                    # under ~5 s there's too little to go on
MIN_OVERLAP = 0.9                 # aligned overlap must cover this much of each track

# Thresholds, measured on real libraries: re-encodes of one master score
# 0.00-0.05 overall with no 2.5 s window above ~0.09; edited versions (explicit vs
# clean) score 0.03-0.10 overall but have windows of 0.17+; different mixes and
# different songs score 0.25 and up.
SAME_MAX_BER = 0.10
SAME_MAX_BLOCK_BER = 0.13
VARIANT_MAX_BER = 0.20

if hasattr(np, 'bitwise_count'):
    def _popcount(x: np.ndarray) -> np.ndarray:
        return np.bitwise_count(x)
else:  # numpy < 2.0
    _POP8 = np.array([bin(i).count('1') for i in range(256)], dtype=np.uint8)

    def _popcount(x: np.ndarray) -> np.ndarray:
        return _POP8[x.view(np.uint8)].reshape(*x.shape, 4).sum(axis=-1)


_POP8_TABLE = np.array([bin(i).count('1') for i in range(256)], dtype=np.uint8)
_popcount8 = np.bitwise_count if hasattr(np, 'bitwise_count') else (lambda x: _POP8_TABLE[x])


class FingerprintError(Exception):
    """The file could not be fingerprinted (corrupt, unsupported, not audio)."""


class FingerprintTimeout(FingerprintError):
    """fpcalc took too long. Treated as transient: never cached."""


def fpcalc_version() -> str | None:
    """Returns the fpcalc version line, or None if fpcalc isn't installed."""
    exe = shutil.which('fpcalc')
    if not exe:
        return None
    try:
        r = subprocess.run([exe, '-version'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout or r.stderr).strip() or 'fpcalc'


def run_fpcalc(path: str, timeout: float = 300) -> tuple[float, np.ndarray]:
    """Fingerprints the whole file. Returns (duration_seconds, fingerprint)."""
    try:
        r = subprocess.run(['fpcalc', '-raw', '-json', '-length', '0', path],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FingerprintTimeout(f"fpcalc timed out after {timeout:g}s") from e
    except OSError as e:
        raise FingerprintError(f"could not run fpcalc: {e}") from e
    if r.returncode != 0:
        msg = (r.stderr or '').strip().splitlines()
        raise FingerprintError(msg[-1] if msg else f"fpcalc exited with status {r.returncode}")
    try:
        data = json.loads(r.stdout)
        values = data['fingerprint']
        duration = float(data['duration'])
    except (ValueError, KeyError, TypeError) as e:
        raise FingerprintError(f"unexpected fpcalc output: {e}") from e
    # Older fpcalc versions print raw values as signed integers.
    fp = np.array(values, dtype=np.int64).astype(np.uint32)
    return duration, fp


def is_low_information(fp: np.ndarray) -> bool:
    """True for fingerprints that can't identify anything on their own: very short
    tracks, silence, and near-constant tones, which all look alike."""
    if len(fp) < MIN_ITEMS:
        return True
    _, counts = np.unique(fp, return_counts=True)
    return len(counts) < 0.15 * len(fp) or counts.max() > 0.5 * len(fp)


@dataclass(frozen=True)
class Comparison:
    ber: float          # fraction of differing bits over the aligned overlap
    max_block_ber: float  # worst ~2.5 s window
    offset: int         # alignment, in items (positive: a starts later)
    max_block_at: float = 0.0  # seconds into a where the worst window starts

    @property
    def kind(self) -> str:
        """'same' (the same audio), 'variant' (same recording, edited somewhere),
        or 'different'."""
        if self.ber <= SAME_MAX_BER and self.max_block_ber <= SAME_MAX_BLOCK_BER:
            return 'same'
        if self.ber <= VARIANT_MAX_BER:
            return 'variant'
        return 'different'


def _best_offset(a: np.ndarray, b: np.ndarray) -> tuple[int, float] | None:
    """Finds the alignment of a short window of a within b. Returns (offset, ber)."""
    n = min(len(a), len(b))
    width = min(PREFILTER_ITEMS, n - 2 * MAX_OFFSET)
    if width < MIN_ITEMS // 2:
        width = n - 2 * MAX_OFFSET
        if width <= 0:
            return None
    start = max(MAX_OFFSET, min(n // 4, n - width - MAX_OFFSET))
    window = a[start:start + width]
    lo, hi = start - MAX_OFFSET, start + MAX_OFFSET + width
    if lo < 0 or hi > len(b):
        return None
    candidates = np.lib.stride_tricks.sliding_window_view(b[lo:hi], width)
    bers = _popcount(candidates ^ window).sum(axis=1) / (32.0 * width)
    i = int(np.argmin(bers))
    # candidates[i] starts at b[lo + i], so b is shifted by (lo + i - start) relative to a.
    return start - (lo + i), float(bers[i])


# The batched pre-test estimates the window error from the low 8 bits of each value:
# 1,280 bits, accurate to about +-1.5%, against unrelated tracks at ~50%. Its cut-off is
# a little looser than the exact test's, so it only ever lets more pairs through to
# the full comparison, never fewer.
FAST_PREFILTER_MAX_BER = PREFILTER_MAX_BER + 0.03


def prefilter_many(a: np.ndarray, bs: list[np.ndarray]) -> list[bool]:
    """For each b: could a and b be the same audio? The same window search as
    _best_offset, for all candidates in one numpy operation and on 8 bits per value,
    because comparing large libraries is dominated by this test."""
    out = [False] * len(bs)
    span = PREFILTER_ITEMS + 2 * MAX_OFFSET
    idx, segs_a, segs_b = [], [], []
    for k, b in enumerate(bs):
        n = min(len(a), len(b))
        if n < MIN_ITEMS:
            continue
        if n - 2 * MAX_OFFSET < PREFILTER_ITEMS:
            # Short track: the window shrinks, so do it the ordinary way.
            found = _best_offset(a, b)
            out[k] = found is not None and found[1] <= PREFILTER_MAX_BER
            continue
        start = max(MAX_OFFSET, min(n // 4, n - PREFILTER_ITEMS - MAX_OFFSET))
        lo = start - MAX_OFFSET
        if lo + span > len(b):
            continue
        idx.append(k)
        segs_a.append(a[start:start + PREFILTER_ITEMS])
        segs_b.append(b[lo:lo + span])
    if idx:
        wa = np.stack(segs_a).astype(np.uint8)                                  # (k, W), low byte
        wb = np.lib.stride_tricks.sliding_window_view(
            np.stack(segs_b).astype(np.uint8), PREFILTER_ITEMS, axis=1)         # (k, 2M+1, W)
        bers = _popcount8(wb ^ wa[:, None, :]).sum(axis=2, dtype=np.int32).min(axis=1) / (8.0 * PREFILTER_ITEMS)
        for k, ok in zip(idx, bers <= FAST_PREFILTER_MAX_BER, strict=True):
            out[k] = bool(ok)
    return out


def compare(a: np.ndarray, b: np.ndarray) -> Comparison | None:
    """Compares two fingerprints. Returns None if they can't be the same audio."""
    if min(len(a), len(b)) < MIN_ITEMS:
        return None
    found = _best_offset(a, b)
    if found is None or found[1] > PREFILTER_MAX_BER:
        return None
    offset = found[0]
    x, y = (a[offset:], b) if offset >= 0 else (a, b[-offset:])
    n = min(len(x), len(y))
    if n < MIN_OVERLAP * max(len(a), len(b)):
        return None
    bits = _popcount(x[:n] ^ y[:n]).astype(np.float64)
    ber = float(bits.mean() / 32)
    nblocks = n // BLOCK_ITEMS
    if nblocks:
        blocks = bits[:nblocks * BLOCK_ITEMS].reshape(nblocks, BLOCK_ITEMS).mean(axis=1) / 32
        worst = int(np.argmax(blocks))
        max_block = float(blocks[worst])
        at = (worst * BLOCK_ITEMS + max(offset, 0)) * ITEM_SECONDS
    else:
        max_block, at = ber, 0.0
    return Comparison(ber=ber, max_block_ber=max_block, offset=offset, max_block_at=at)


def compare_profile(a: np.ndarray, b: np.ndarray) -> dict | None:
    """The full comparison for display: per-window difference over time."""
    c = compare(a, b)
    if c is None:
        return None
    x, y = (a[c.offset:], b) if c.offset >= 0 else (a, b[-c.offset:])
    n = min(len(x), len(y))
    bits = _popcount(x[:n] ^ y[:n]).astype(np.float64)
    nblocks = max(1, n // BLOCK_ITEMS)
    blocks = bits[:nblocks * BLOCK_ITEMS].reshape(nblocks, -1).mean(axis=1) / 32
    return {
        'kind': c.kind, 'ber': round(c.ber, 4), 'max_window_ber': round(c.max_block_ber, 4),
        'offset_seconds': round(c.offset * ITEM_SECONDS, 3),
        'window_seconds': round(BLOCK_ITEMS * ITEM_SECONDS, 3),
        'start_seconds': round(max(c.offset, 0) * ITEM_SECONDS, 3),
        'windows': [round(float(v), 3) for v in blocks],
        'thresholds': {'same_max_ber': SAME_MAX_BER, 'same_max_window_ber': SAME_MAX_BLOCK_BER,
                       'variant_max_ber': VARIANT_MAX_BER},
    }
