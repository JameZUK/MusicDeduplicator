import pytest

from musicdedup.editions import (
    accidental_copy,
    base_title,
    edition_markers,
    is_disc_folder,
    release_of,
    same_edition,
)


@pytest.mark.parametrize('text, markers', [
    ('Sounds of the Universe (Deluxe) [2009]', {'deluxe'}),
    ('[E] Sounds of the Universe (Deluxe Edition)', {'deluxe'}),
    ('The Gift [Deluxe Edition] (2023 Remaster)', {'deluxe', 'remaster'}),
    ('Wither ReWired [E]', set()),
    ('Dreams Of The Machine (2026)', set()),
    ('Live at the Palladium', {'live'}),
    ('Greatest Hits Box Set', {'box set'}),
])
def test_edition_markers(text, markers):
    assert edition_markers(text) == markers


@pytest.mark.parametrize('a, b', [
    ('Dreams Of The Machine', 'Dreams Of The Machine (2026)'),
    ('Count Your Blessings  Repented [E]', 'Count Your Blessings Repented (2026)'),
    ('Death & Love', 'Death and Love'),
    ('Sounds of the Universe', '[E] Sounds of the Universe (Deluxe) [2009]'),
])
def test_base_title_ignores_noise(a, b):
    assert base_title(a) == base_title(b)


def test_disc_folders():
    for name in ('CD 1', 'CD1', 'Disc 2', 'disk 03', 'CD 01'):
        assert is_disc_folder(name)
    for name in ('CDs I Like', 'Discovery', 'Album'):
        assert not is_disc_folder(name)


def test_release_uses_tags_then_folder_names():
    r = release_of('/m/Artist/Album (Deluxe)/CD 1', ['Album', 'Album', ''])
    assert r.title == 'album' and r.editions == {'deluxe'}
    r = release_of('/m/Artist/Some Folder', [])
    assert r.title == 'some folder' and not r.editions


def test_same_edition():
    std = release_of('/m/A/Album', ['Album'])
    dlx = release_of('/m/A/Album (Deluxe)', ['Album (Deluxe)'])
    copy = release_of('/m/A/Album (2026)', ['Album'])
    assert same_edition(std, copy)
    assert not same_edition(std, dlx)


@pytest.mark.parametrize('keep, other, expected', [
    (('01 Song.flac', 1, 0), ('01 Song.mp3', 1, 0), True),        # same track, two formats
    (('Song.flac', 0, 0), ('Song (1).flac', 0, 0), True),          # download duplicate
    (('Song.flac', 0, 0), ('Song copy.flac', 0, 0), True),
    (('11. A.flac', 11, 0), ('11. A (Mix).flac', 11, 0), True),    # same track number
    (('17. A.flac', 17, 0), ('19. A.flac', 19, 0), False),         # repeated in the track list
    (('01. A.flac', 1, 1), ('01. A.flac', 1, 2), False),           # different discs
    (('Scut.flac', 0, 0), ('Scut 2.flac', 0, 0), False),           # a real title, no evidence
])
def test_accidental_copy(keep, other, expected):
    assert accidental_copy(*keep, *other) is expected
