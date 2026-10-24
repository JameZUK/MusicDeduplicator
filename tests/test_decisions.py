import os

import pytest
from conftest import FLAC16, FLAC24, MP3_320, noisy, rel

from musicdedup.decisions import DecisionError, apply_decisions
from musicdedup.executor import apply_plan


def group_of(plan, keep):
    return next(g for g in plan['groups'] if rel(plan, g['keep']) == keep)


def folders_removed(plan):
    return {rel(plan, os.path.dirname(r['path'])) for r in plan['removals']}


@pytest.fixture
def three_copies(lib):
    lib.album('A/Album hires', [1, 2, 3], FLAC24)
    lib.album('B/Album', [1, 2, 3], FLAC16)
    lib.album('C/Album mp3', [1, 2, 3], MP3_320, transform=lambda fp: noisy(fp, 0.02), ext='mp3')
    lib.extra('A/Album hires/cover.jpg')
    lib.extra('B/Album/cover.jpg')
    return lib


def test_undecided_groups_remove_nothing(three_copies):
    _, _, plan = three_copies.scan()
    new, _ = apply_decisions(plan, {})
    assert new['removals'] == [] and new['summary']['files_to_remove'] == 0


def test_accept_and_skip(three_copies):
    _, _, plan = three_copies.scan()
    g = group_of(plan, 'A/Album hires')
    new, _ = apply_decisions(plan, {'groups': {str(g['id']): 'accept'}})
    assert folders_removed(new) == {'B/Album', 'C/Album mp3'}
    new, _ = apply_decisions(plan, {'groups': {str(g['id']): 'skip'}})
    assert new['removals'] == []


def test_choose_a_different_keeper(three_copies, tmp_path):
    _, _, plan = three_copies.scan()
    g = group_of(plan, 'A/Album hires')
    new, warnings = apply_decisions(plan, {'groups': {g['id']: {'keep': three_copies.path('B/Album')}}})
    assert folders_removed(new) == {'A/Album hires', 'C/Album mp3'}
    for r in new['removals']:
        if r['keep']:
            assert rel(new, r['keep']['path']).startswith('B/Album/')
    assert any('lower-quality' in w for w in warnings)        # the hi-res copy goes
    assert any(rel(new, r['path']) == 'A/Album hires/cover.jpg' for r in new['removals'])
    assert not any(rel(new, r['path']) == 'B/Album/cover.jpg' for r in new['removals'])
    result = apply_plan(new, mode='move', move_to=str(tmp_path / 'q'))
    assert not result.skipped
    assert sorted(os.listdir(three_copies.path('B/Album'))) == ['01.flac', '02.flac', '03.flac', 'cover.jpg']
    assert not os.path.exists(three_copies.path('A/Album hires'))


def test_a_folder_with_missing_tracks_cannot_become_keeper(lib):
    lib.album('A/Album', [1, 2, 3], album='Album')
    lib.album('B/Album (2026)', [1, 2], album='Album')
    _, _, plan = lib.scan()
    g = plan['groups'][0]
    with pytest.raises(DecisionError):
        apply_decisions(plan, {'groups': {g['id']: {'keep': lib.path('B/Album (2026)')}}})


def test_other_folders_the_new_keeper_cannot_cover_are_kept(lib):
    lib.album('A/Album', [1, 2, 3], album='Album')
    lib.album('B/Album copy', [1, 2, 3], album='Album')
    lib.album('C/Album (2026)', [1, 2], album='Album')
    _, _, plan = lib.scan()
    g = group_of(plan, 'A/Album')
    new, warnings = apply_decisions(plan, {'groups': {g['id']: {'keep': lib.path('B/Album copy')}}})
    assert folders_removed(new) == {'A/Album', 'C/Album (2026)'}  # C's tracks are all in B too
    assert not warnings


def test_within_folder_removals_need_listing(lib):
    lib.album('A/Album', [1, 2])
    from conftest import make_fp
    p = lib.add('A/Album/01.mp3', noisy(make_fp(1), 0.02), MP3_320, track=1)
    _, _, plan = lib.scan(within_folders=True)
    assert apply_decisions(plan, {})[0]['removals'] == []
    new, _ = apply_decisions(plan, {'within': [os.path.realpath(p)]})
    assert [rel(new, r['path']) for r in new['removals']] == ['A/Album/01.mp3']


def test_unknown_group_is_an_error(three_copies):
    _, _, plan = three_copies.scan()
    with pytest.raises(DecisionError):
        apply_decisions(plan, {'groups': {'999': 'accept'}})
