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


# Appended to the error of a file that failed both ways, so a rescan doesn't retry it.
FALLBACK_FAILED = '(also unreadable through ffmpeg)'
FALLBACK_RATE = 11025


def _parse_fpcalc(stdout: str) -> tuple[float, np.ndarray]:
    try:
        data = json.loads(stdout)
        values = data['fingerprint']
        duration = float(data['duration'])
    except (ValueError, KeyError, TypeError) as e:
        raise FingerprintError(f"unexpected fpcalc output: {e}") from e
    # Older fpcalc versions print raw values as signed integers.
    return duration, np.array(values, dtype=np.int64).astype(np.uint32)


def _fpcalc_via_ffmpeg(path: str, timeout: float) -> tuple[float, np.ndarray]:
    """Decodes with ffmpeg, skipping damaged frames, and fingerprints the raw audio.
    fpcalc on its own gives up at the first decoding error, which a single bad frame
    in an otherwise playable file causes."""
    try:
        pcm = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-err_detect', 'ignore_err', '-i', path,
                              '-vn', '-ac', '1', '-ar', str(FALLBACK_RATE), '-f', 's16le', '-'],
                             capture_output=True, timeout=timeout).stdout
        if len(pcm) < 2 * FALLBACK_RATE:
            raise FingerprintError("no audio could be decoded")
        r = subprocess.run(['fpcalc', '-raw', '-json', '-length', '0', '-format', 's16le',
                            '-rate', str(FALLBACK_RATE), '-channels', '1', '-'],
                           input=pcm, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FingerprintTimeout(f"decoding timed out after {timeout:g}s") from e
    except OSError as e:
        raise FingerprintError(f"could not run ffmpeg: {e}") from e
    if r.returncode != 0:
        raise FingerprintError("fpcalc could not fingerprint the decoded audio")
    _, fp = _parse_fpcalc(r.stdout.decode(errors='replace'))
    # fpcalc can't know the duration of raw input; it's the amount of audio decoded.
    return len(pcm) / (2 * FALLBACK_RATE), fp


def run_fpcalc(path: str, timeout: float = 300) -> tuple[float, np.ndarray, bool]:
    """Fingerprints the whole file. Returns (duration_seconds, fingerprint, damaged):
    damaged means fpcalc couldn't decode it but ffmpeg could, skipping bad frames."""
    try:
        r = subprocess.run(['fpcalc', '-raw', '-json', '-length', '0', path],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FingerprintTimeout(f"fpcalc timed out after {timeout:g}s") from e
    except OSError as e:
        raise FingerprintError(f"could not run fpcalc: {e}") from e
    if r.returncode == 0:
        duration, fp = _parse_fpcalc(r.stdout)
        return duration, fp, False
    msg = (r.stderr or '').strip().splitlines()
    error = msg[-1] if msg else f"fpcalc exited with status {r.returncode}"
    if not shutil.which('ffmpeg'):
        raise FingerprintError(error)
    try:
        duration, fp = _fpcalc_via_ffmpeg(path, timeout)
    except FingerprintTimeout:
        raise
    except FingerprintError as e:
        raise FingerprintError(f"{error} {FALLBACK_FAILED}") from e
    return duration, fp, True


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
    gap: bool = False          # same audio apart from a damaged, skipped stretch

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


GAP_SEARCH = 8          # items (~1 s) either side when re-aligning after a damaged spot
GAP_MAX_BAD_BLOCKS = 3  # ~7.5 s of damaged audio at most


def _same_but_for_a_gap(a: np.ndarray, b: np.ndarray, offset: int) -> bool:
    """For a copy known to be damaged: is it the same audio apart from one short damaged
    spot? A decoder skipping bad frames shortens the audio after it, so the rest only
    lines up again at a slightly different offset. Checked per ~2.5 s block: every block
    must match well at one of two offsets (before and after the spot), with at most a
    few bad blocks, all together, where the offset changes."""
    blocks = min(len(a), len(b)) // BLOCK_ITEMS
    if blocks < 4:
        return False
    best_ber, best_off = [], []
    for k in range(blocks):
        s = k * BLOCK_ITEMS
        wa = a[s:s + BLOCK_ITEMS]
        found = None
        for o in range(offset - GAP_SEARCH, offset + GAP_SEARCH + 1):
            lo = s - o
            if lo < 0 or lo + BLOCK_ITEMS > len(b):
                continue
            ber = float(_popcount(wa ^ b[lo:lo + BLOCK_ITEMS]).sum() / (32.0 * BLOCK_ITEMS))
            if found is None or ber < found[0]:
                found = (ber, o)
        if found is None:
            return False
        best_ber.append(found[0])
        best_off.append(found[1])
    bad = [k for k, ber in enumerate(best_ber) if ber > SAME_MAX_BLOCK_BER]
    if len(bad) > GAP_MAX_BAD_BLOCKS or (bad and bad[-1] - bad[0] >= len(bad) + 1):
        return False
    good = [k for k in range(blocks) if k not in bad]
    if not good or float(np.mean([best_ber[k] for k in good])) > SAME_MAX_BER:
        return False
    # Good blocks: one offset before the spot and one after (ignore near-silent blocks,
    # whose best offset is arbitrary).
    # The signature of skipped frames: one offset before the spot and a different one
    # after it. Without that shift it's a change to the audio itself (an edit), which
    # this never excuses. Near-silent blocks are ignored: their best offset is arbitrary.
    sure = [k for k in good if best_ber[k] < SAME_MAX_BER]
    seq = [best_off[k] for k in sure]
    changes = [i for i in range(1, len(seq)) if seq[i] != seq[i - 1]]
    if len(changes) != 1:
        return False
    switch = sure[changes[0]]
    if bad and not (sure[changes[0] - 1] < bad[0] and switch > bad[-1]):
        return False   # the shift must happen across the damaged spot
    return True


def compare(a: np.ndarray, b: np.ndarray, allow_gap: bool = False) -> Comparison | None:
    """Compares two fingerprints. Returns None if they can't be the same audio.
    allow_gap: one of them is known to be damaged, so a single skipped stretch is
    tolerated (see _same_but_for_a_gap). Never set it for two clean files: a deliberate
    edit that cuts something out would then look like the same audio."""
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
    c = Comparison(ber=ber, max_block_ber=max_block, offset=offset, max_block_at=at)
    if allow_gap and c.kind != 'same' and ber <= 2 * VARIANT_MAX_BER and _same_but_for_a_gap(a, b, offset):
        # Report it as same audio; the damage itself is shown elsewhere (the file is flagged).
        return Comparison(ber=min(ber, SAME_MAX_BER), max_block_ber=min(max_block, SAME_MAX_BLOCK_BER),
                          offset=offset, max_block_at=at, gap=True)
    return c


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
