"""End to end with real fpcalc and ffmpeg on synthesised music: scan, apply, undo."""

import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np
import pytest

from musicdedup.cli import main

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('fpcalc')),
                       reason="needs ffmpeg and fpcalc"),
]

RATE = 22050


def melody(seed: int, seconds: float = 40.0) -> np.ndarray:
    """Seeded random notes with harmonics: different seeds sound like different songs."""
    rng = np.random.default_rng(seed)
    out = []
    while sum(len(n) for n in out) < seconds * RATE:
        freq = 110 * 2 ** (rng.integers(0, 36) / 12)
        t = np.arange(int(rng.uniform(0.15, 0.6) * RATE)) / RATE
        note = sum(np.sin(2 * np.pi * freq * k * t) / k for k in (1, 2, 3, 4))
        out.append(note * np.minimum(1, np.minimum(t, t[::-1]) * 40))
    return np.concatenate(out)[:int(seconds * RATE)]


def write_audio(path: str, samples: np.ndarray, codec: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wav = path + '.wav'
    with wave.open(wav, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((samples / np.abs(samples).max() * 20000).astype('<i2').tobytes())
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', wav, *codec, path], check=True)
    os.remove(wav)


FLAC = ['-c:a', 'flac']
MP3 = ['-c:a', 'libmp3lame', '-b:a', '128k']


@pytest.fixture(scope='module')
def library(tmp_path_factory):
    root = tmp_path_factory.mktemp('integration') / 'music'
    songs = {s: melody(s) for s in (1, 2, 3, 4)}
    for i, s in enumerate((1, 2, 3), 1):
        write_audio(f'{root}/Artist/Album/{i:02d}.flac', songs[s], FLAC)
        write_audio(f'{root}/Artist/Album (2026)/{i:02d}.mp3', songs[s], MP3)
        write_audio(f'{root}/Artist/Album (Deluxe)/{i:02d}.flac', songs[s], FLAC)
    write_audio(f'{root}/Artist/Album (Deluxe)/04.flac', songs[4], FLAC)
    # Clean edit: two seconds of song 2 replaced.
    clean = songs[2].copy()
    clean[15 * RATE:17 * RATE] = melody(99, 2)
    write_audio(f'{root}/Artist/Album (Clean)/01.flac', songs[1], FLAC)
    write_audio(f'{root}/Artist/Album (Clean)/02.flac', clean, FLAC)
    write_audio(f'{root}/Artist/Album (Clean)/03.flac', songs[3], FLAC)
    with open(f'{root}/Artist/Album (2026)/cover.jpg', 'wb') as f:
        f.write(b'jpeg')
    return str(root)


def snapshot(root):
    return {os.path.relpath(os.path.join(d, f), root): os.path.getsize(os.path.join(d, f))
            for d, _, fs in os.walk(root) for f in fs}


def test_scan_apply_undo(library, tmp_path, capsys):
    before = snapshot(library)
    plan_path = str(tmp_path / 'plan.json')
    assert main(['scan', library, '-o', plan_path, '--cache', str(tmp_path / 'c.db'), '-q']) == 0
    plan = json.load(open(plan_path))
    rel = lambda p: os.path.relpath(p, library)  # noqa: E731

    # The MP3 copy is a duplicate of the FLAC standard album.
    assert [(rel(g['keep']), [rel(r['folder']) for r in g['remove']]) for g in plan['groups']] == [
        ('Artist/Album', ['Artist/Album (2026)'])]
    # The standard album is inside the deluxe, but it's a different edition: kept.
    assert [rel(e['folder']) for e in plan['smaller_editions_kept']] == ['Artist/Album']
    # The clean edit is recognised against each of the three other copies, and located.
    variants = plan['edited_versions']
    assert len(variants) == 3
    for v in variants:
        assert 'Artist/Album (Clean)/02.flac' in {rel(p) for p in v['paths']}
        assert v['differs_at'] in ('0:13', '0:14', '0:15', '0:16')
    assert snapshot(library) == before   # scanning changed nothing

    q = str(tmp_path / 'quarantine')
    assert main(['apply', plan_path, '--move-to', q, '--yes', '-q']) == 0
    assert not os.path.exists(f'{library}/Artist/Album (2026)')
    assert sorted(snapshot(q + '/music')) == ['Artist/Album (2026)/01.mp3', 'Artist/Album (2026)/02.mp3',
                                              'Artist/Album (2026)/03.mp3', 'Artist/Album (2026)/cover.jpg']
    [journal] = [f for f in os.listdir(q) if f.startswith('musicdedup-journal-')]
    assert main(['undo', os.path.join(q, journal), '-q']) == 0
    assert snapshot(library) == before


def test_rescan_uses_cache(library, tmp_path):
    cache = str(tmp_path / 'c.db')
    main(['scan', library, '-o', str(tmp_path / 'p1.json'), '--cache', cache, '-q'])
    main(['scan', library, '-o', str(tmp_path / 'p2.json'), '--cache', cache, '-q'])
    s = json.load(open(tmp_path / 'p2.json'))['summary']
    assert s['from cache'] == s['audio_files'] and 'fingerprinted' not in s


def test_apply_refuses_without_confirmation_when_not_interactive(library, tmp_path, monkeypatch):
    plan_path = str(tmp_path / 'plan.json')
    main(['scan', library, '-o', plan_path, '--no-cache', '-q'])
    monkeypatch.setattr(sys, 'stdin', open(os.devnull))
    before = snapshot(library)
    assert main(['apply', plan_path, '--delete', '-q']) == 1
    assert snapshot(library) == before


def test_legacy_wrapper_lists(library, tmp_path):
    script = os.path.join(os.path.dirname(__file__), '..', 'musicorganise.py')
    env = {**os.environ, 'XDG_CACHE_HOME': str(tmp_path)}
    r = subprocess.run([sys.executable, script, '-p', library, '-a', 'list'],
                       cwd=tmp_path, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert 'Album (2026)' in r.stdout and (tmp_path / 'musicdedup-plan.json').exists()


def test_waveform_peaks(library):
    from musicdedup.waveform import waveform
    path = f'{library}/Artist/Album/01.flac'
    st = os.stat(path)
    w = waveform(path, st.st_size, st.st_mtime_ns)
    assert 39 < w['duration'] < 41
    assert len(w['peak']) == pytest.approx(w['duration'] * w['per_second'], abs=1)
    assert max(w['peak']) > 100 and all(0 <= v <= 255 for v in w['peak'])
