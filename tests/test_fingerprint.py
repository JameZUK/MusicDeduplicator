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
