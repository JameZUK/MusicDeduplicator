import os
import random

from conftest import FLAC16, FLAC24, MP3_320, edited, kept_folders, make_fp, noisy, rel, removed_folders


def test_exact_duplicate_album(lib):
    lib.album('A/Album', [1, 2, 3])
    lib.album('B/Album copy', [1, 2, 3])
    _, _, plan = lib.scan()
    assert kept_folders(plan) == {'A/Album'}
    assert removed_folders(plan) == {'B/Album copy'}
    audio = [r for r in plan['removals'] if r['reason'] != 'extra']
    assert len(audio) == 3
    for r in audio:  # every removal names the copy that is kept
        assert os.path.basename(r['path']) == os.path.basename(r['keep']['path'])
        assert rel(plan, r['keep']['path']).startswith('A/Album/')


def test_better_quality_is_kept_whatever_the_path(lib):
    lib.album('A/Album mp3', [1, 2, 3], MP3_320, transform=lambda fp: noisy(fp, 0.02), ext='mp3')
    lib.album('Z/Album flac', [1, 2, 3], FLAC16)
    lib.album('M/Album hires', [1, 2, 3], FLAC24)
    _, _, plan = lib.scan()
    assert kept_folders(plan) == {'M/Album hires'}
    assert removed_folders(plan) == {'A/Album mp3', 'Z/Album flac'}


def test_hires_copy_wins_even_when_it_sorts_last(lib):
    lib.album('A/Album - Remastered (2026)', [1, 2, 3], FLAC16, album='Album')
    lib.album('A/Album [E]', [1, 2, 3], FLAC24, album='Album')
    lib.album('A/Album (2026)', [1, 2, 3], FLAC16, album='Album')
    _, _, plan = lib.scan()
    assert kept_folders(plan) == {'A/Album [E]'}
    assert removed_folders(plan) == {'A/Album - Remastered (2026)', 'A/Album (2026)'}


def test_prefer_does_not_beat_quality(lib):
    lib.album('Library/Album', [1, 2], FLAC16)
    lib.album('Downloads/Album', [1, 2], FLAC24)
    _, _, plan = lib.scan(prefer=[lib.path('Library')])
    assert kept_folders(plan) == {'Downloads/Album'}


def test_lower_quality_superset_does_not_remove_better_subset(lib):
    lib.album('A/Album flac', [1, 2, 3], FLAC16)
    lib.album('B/Album mp3 deluxe', [1, 2, 3, 4], MP3_320, ext='mp3')
    _, _, plan = lib.scan()
    assert plan['removals'] == []
    assert plan['shared_tracks'][0]['shared_tracks'] == 3


def test_incomplete_copy_of_same_edition_is_removed(lib):
    lib.album('A/Album', [1, 2, 3, 4], album='Album')
    lib.album('B/Album (2026)', [1, 2, 3], album='Album')
    _, _, plan = lib.scan()
    assert removed_folders(plan) == {'B/Album (2026)'}
    assert plan['groups'][0]['remove'][0]['kind'] == 'contained'


def test_standard_edition_inside_deluxe_is_kept_unless_asked(lib):
    lib.album('A/Album', [1, 2, 3], album='Album')
    lib.album('A/Album (Deluxe)', [1, 2, 3, 4, 5], album='Album (Deluxe Edition)')
    _, _, plan = lib.scan()
    assert plan['removals'] == []
    [kept] = plan['smaller_editions_kept']
    assert rel(plan, kept['folder']) == 'A/Album'
    assert kept['contained_in_edition'] == 'deluxe'

    _, _, plan = lib.scan(remove_smaller_editions=True)
    assert removed_folders(plan) == {'A/Album'}


def test_deluxe_is_never_stripped_to_match_standard(lib):
    lib.album('A/Album', [1, 2, 3], FLAC24, album='Album')
    lib.album('A/Album (Deluxe)', [1, 2, 3, 4, 5], FLAC16, album='Album (Deluxe)')
    _, _, plan = lib.scan(remove_smaller_editions=True, within_folders=True)
    # The hi-res standard album can't be removed (the deluxe copy is worse), and no
    # tracks are taken out of the deluxe.
    assert plan['removals'] == []


def test_edited_track_means_not_duplicates(lib):
    lib.album('A/Album [E]', [1, 2, 3])
    lib.add('B/Album/01.flac', make_fp(1))
    lib.add('B/Album/02.flac', edited(make_fp(2), 500, 12))
    lib.add('B/Album/03.flac', make_fp(3))
    _, _, plan = lib.scan()
    assert plan['removals'] == []
    assert len(plan['edited_versions']) == 1
    assert plan['shared_tracks'][0]['shared_tracks'] == 2


def test_within_folder_accidental_copy(lib):
    lib.album('A/Album', [1, 2, 3])
    lib.add('A/Album/01.mp3', noisy(make_fp(1), 0.02), MP3_320, track=1)
    _, _, plan = lib.scan()
    assert plan['removals'] == []                       # reported only by default
    assert len(plan['within_folder']) == 1
    _, _, plan = lib.scan(within_folders=True)
    [r] = plan['removals']
    assert r['path'].endswith('01.mp3') and r['keep']['path'].endswith('01.flac')


def test_within_folder_copy_in_a_removed_folder_points_at_the_kept_folder(lib):
    lib.album('A/Album', [1, 2, 3])
    lib.album('B/Album', [1, 2, 3])
    lib.add('B/Album/01 (copy).mp3', noisy(make_fp(1), 0.02), MP3_320)
    _, _, plan = lib.scan(within_folders=True)
    removed = {r['path'] for r in plan['removals']}
    for r in plan['removals']:
        assert r['keep'] is None or r['keep']['path'] not in removed
    copy = next(r for r in plan['removals'] if r['path'].endswith('(copy).mp3'))
    assert rel(plan, copy['keep']['path']) == 'A/Album/01.flac'


def test_repeated_track_in_release_is_kept_intact(lib):
    lib.add('A/Album/17. Song.flac', make_fp(1), track=17)
    lib.add('A/Album/18. Other.flac', make_fp(2), track=18)
    lib.add('A/Album/19. Song.flac', make_fp(1), track=19)
    _, _, plan = lib.scan(within_folders=True)
    assert plan['removals'] == []
    assert len(plan['repeated_in_release']) == 1


def test_within_folder_copy_does_not_make_a_folder_bigger(lib):
    lib.album('A/Album', [1, 2, 3])
    lib.album('B/Album', [1, 2, 3])
    lib.add('B/Album/01 (1).flac', make_fp(1))
    _, _, plan = lib.scan()
    # Same distinct audio: tie broken by path, and B's stray copy goes with B.
    assert kept_folders(plan) == {'A/Album'}
    assert removed_folders(plan) == {'B/Album'}
    assert plan['groups'][0]['remove'][0]['kind'] == 'duplicate'


def test_unreadable_file_blocks_removal(lib):
    lib.album('A/Album', [1, 2, 3])
    lib.album('B/Album', [1, 2, 3])
    lib.add('B/Album/04.flac', None, error='corrupt')
    _, _, plan = lib.scan()
    assert plan['removals'] == []
    assert rel(plan, plan['blocked'][0]['folder']) == 'B/Album'
    assert plan['unreadable'][0]['error'] == 'corrupt'


def test_silence_alone_is_not_a_duplicate(lib):
    silence = make_fp(0, 600) & 0
    lib.add('A/Intro/01.flac', silence)
    lib.add('B/Intro/01.flac', silence.copy())
    _, _, plan = lib.scan()
    assert plan['removals'] == []


def test_hidden_silent_track_does_not_stop_an_album_match(lib):
    silence = make_fp(0, 600) & 0
    for folder in ('A/Album', 'B/Album'):
        lib.album(folder, [1, 2])
        lib.add(f'{folder}/03.flac', silence.copy())
    _, _, plan = lib.scan()
    assert removed_folders(plan) == {'B/Album'}


def test_prefer_breaks_ties(lib):
    lib.album('A/Album', [1, 2])
    lib.album('Downloads/Album', [1, 2])
    _, _, plan = lib.scan(prefer=[lib.path('Downloads')])
    assert kept_folders(plan) == {'Downloads/Album'}


def test_keeper_with_best_copies_is_chosen(lib):
    lib.album('A/Album copy', [1, 2, 3, 99], FLAC16)        # bigger folder, same quality
    lib.album('B/Album [E]', [1, 2, 3], FLAC24)             # same tracks, hi-res
    lib.album('C/Album', [1, 2, 3], FLAC16)
    _, _, plan = lib.scan()
    group = next(g for g in plan['groups'] if any(rel(plan, r['folder']) == 'C/Album' for r in g['remove']))
    assert rel(plan, group['keep']) == 'B/Album [E]'


def test_extras_go_with_a_removed_folder(lib):
    lib.album('A/Album', [1, 2])
    lib.album('B/Album', [1, 2])
    lib.extra('B/Album/cover.jpg')
    lib.extra('A/Album/cover.jpg')
    _, _, plan = lib.scan()
    extras = [r for r in plan['removals'] if r['reason'] == 'extra']
    assert [rel(plan, r['path']) for r in extras] == ['B/Album/cover.jpg']


def test_plan_is_deterministic(lib):
    for folder in ('A/X', 'B/X', 'C/X', 'D/Y'):
        lib.album(folder, [1, 2, 3] if folder != 'D/Y' else [1, 2])
    result, matches, plan = lib.scan()
    from musicdedup.matcher import find_matches
    from musicdedup.planner import build_plan
    for seed in range(5):
        random.Random(seed).shuffle(result.tracks)
        again = build_plan(result, find_matches(result.tracks))
        assert [r['path'] for r in again['removals']] == [r['path'] for r in plan['removals']]
        assert [g['keep'] for g in again['groups']] == [g['keep'] for g in plan['groups']]
