import numpy as np
import pytest
from conftest import edited, make_fp, noisy

from musicdedup.fingerprint import BLOCK_ITEMS, ITEM_SECONDS, compare, is_low_information


def test_identical_is_same():
    fp = make_fp(1)
    c = compare(fp, fp.copy())
    assert c.kind == 'same' and c.ber == 0 and c.offset == 0


@pytest.mark.parametrize('ber', [0.01, 0.03, 0.06])
def test_reencode_noise_is_same(ber):
    fp = make_fp(1)
    assert compare(fp, noisy(fp, ber)).kind == 'same'


@pytest.mark.parametrize('shift', [-6, -1, 2, 8])
def test_alignment_offset_is_found(shift):
    fp = make_fp(2, 1600)
    a, b = (fp[shift:], fp) if shift > 0 else (fp, fp[-shift:])
    c = compare(a, b)
    assert c.kind == 'same'
    assert c.offset == -shift


def test_local_edit_is_variant_and_located():
    fp = make_fp(3)
    start = 600
    c = compare(fp, edited(fp, start, 12))
    assert c.kind == 'variant'
    # The worst window covers the edit.
    assert abs(c.max_block_at - start * ITEM_SECONDS) <= 2 * BLOCK_ITEMS * ITEM_SECONDS


def test_different_songs_do_not_match():
    c = compare(make_fp(4), make_fp(5))
    assert c is None or c.kind == 'different'


def test_mostly_different_mix_is_not_a_variant():
    a = make_fp(6)
    assert compare(a, noisy(a, 0.25)).kind == 'different'


def test_large_length_difference_is_not_compared():
    fp = make_fp(7, 2000)
    assert compare(fp, fp[:1000]) is None


def test_too_short_is_not_compared():
    fp = make_fp(8, 20)
    assert compare(fp, fp) is None


def test_low_information():
    assert is_low_information(np.zeros(500, dtype=np.uint32))
    assert is_low_information(make_fp(9, 30))
    tone = np.tile(make_fp(10, 3), 200)
    assert is_low_information(tone)
    assert not is_low_information(make_fp(11))


def test_batched_prefilter_never_rejects_what_the_pairwise_test_accepts():
    """prefilter_many may let a few extra pairs through, but never fewer."""
    from musicdedup.fingerprint import PREFILTER_MAX_BER, _best_offset, prefilter_many
    rng = np.random.default_rng(5)
    a = make_fp(1, 1800)
    bs = []
    for k in range(120):
        kind = k % 6
        if kind == 0:
            b = noisy(a, rng.uniform(0, 0.12), seed=k)
        elif kind == 1:
            b = edited(a, 400, 30, seed=k)
        elif kind == 2:
            b = noisy(a, 0.25, seed=k)
        elif kind == 3:
            shift = int(rng.integers(-9, 10))
            b = a[shift:] if shift >= 0 else np.concatenate([make_fp(k, -shift), a])
        elif kind == 4:
            b = make_fp(100 + k, int(rng.integers(1700, 1900)))
        else:
            b = make_fp(200 + k, int(rng.integers(30, 200)))   # short: the fallback path
        bs.append(b)
    expected = []
    for b in bs:
        found = _best_offset(a, b) if min(len(a), len(b)) >= 40 else None
        expected.append(found is not None and found[1] <= PREFILTER_MAX_BER)
    got = prefilter_many(a, bs)
    assert all(g for g, e in zip(got, expected, strict=True) if e)
    assert sum(got) <= sum(expected) + 2                  # and it still rejects unrelated tracks
    assert any(expected) and not all(got)


def test_damaged_copy_with_a_skipped_stretch_is_same_only_when_allowed():
    fp = make_fp(12, 1600)
    skipped = np.concatenate([fp[:800], fp[803:]])          # three items lost at a damaged spot
    assert compare(fp, skipped).kind != 'same'              # clean files: strict
    c = compare(fp, skipped, allow_gap=True)
    assert c.kind == 'same' and c.gap


def test_an_edit_is_never_excused_as_a_gap():
    fp = make_fp(13, 1600)
    censored = edited(fp, 700, 12)                           # changed, not shifted
    assert compare(fp, censored, allow_gap=True).kind == 'variant'
    different = make_fp(14, 1600)
    c = compare(fp, different, allow_gap=True)
    assert c is None or c.kind == 'different'
