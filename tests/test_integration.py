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


def test_dashboard_scans_without_a_plan_and_carries_decisions(library, tmp_path, monkeypatch):
    import threading
    import time
    import urllib.request

    from musicdedup.planner import Options
    from musicdedup.web.access import AccessPolicy
    from musicdedup.web.server import App, make_server

    lib = tmp_path / 'lib'
    shutil.copytree(library, lib)
    plan_path = tmp_path / 'plan.json'
    app = App(str(plan_path), AccessPolicy(), state_dir=str(tmp_path / 'state'), cache_path=str(tmp_path / 'c.db'),
              move_to=None, allow_delete=False, library=[str(lib)], scan_options=Options())
    srv = make_server(app, '127.0.0.1', 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_address[1]}'

    def call(path, body=None):
        token = json.load(urllib.request.urlopen(base + '/api/session'))['csrf']
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     method='POST' if body is not None else 'GET',
                                     headers={'Content-Type': 'application/json', 'X-CSRF-Token': token})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def scan_and_wait():
        assert call('/api/scan', {})[0] == 202
        for _ in range(300):
            st = call('/api/scan')[1]
            if st['state'] != 'running':
                return st
            time.sleep(0.1)
        raise AssertionError('scan did not finish')

    try:
        session = call('/api/session')[1]
        assert session['has_plan'] is False and session['can_scan'] is True
        assert call('/api/plan')[0] == 503
        st = scan_and_wait()
        assert st['state'] == 'done' and st['summary']['tracks'] == 13
        plan = call('/api/plan')[1]
        assert plan['new_music']['first_scan'] and plan['library']['tracks'] == 13
        gid = str(plan['groups'][0]['id'])
        req = urllib.request.Request(base + '/api/decisions', method='PUT',
                                     data=json.dumps({'groups': {gid: 'accept'}}).encode(),
                                     headers={'Content-Type': 'application/json',
                                              'X-CSRF-Token': call('/api/session')[1]['csrf']})
        urllib.request.urlopen(req)

        write_audio(f'{lib}/Artist/New Single/01.flac', melody(42), FLAC)
        time.sleep(1.1)   # the plan's "created" time is per second
        st = scan_and_wait()
        assert st['summary']['new'] == 1
        plan = call('/api/plan')[1]
        assert [os.path.relpath(f['folder'], lib) for f in plan['new_music']['folders']] == ['Artist/New Single']
        assert call('/api/decisions')[1]['groups'] == {gid: 'accept'}   # carried over
        assert len(call('/api/scans')[1]) == 2
    finally:
        srv.shutdown()
        srv.server_close()


def test_new_music_after_a_stopped_scan(library, tmp_path):
    import threading

    from musicdedup.pipeline import run_scan
    from musicdedup.planner import Options
    from musicdedup.scanner import ScanCancelled

    lib = tmp_path / 'lib'
    shutil.copytree(library, lib)
    kw = dict(plan_path=str(tmp_path / 'p.json'), cache_path=str(tmp_path / 'c.db'), options=Options(),
              state_dir=str(tmp_path / 'state'))
    stop = threading.Event()
    seen = []

    def progress(stage, done, total):
        seen.append(stage)
        if stage == 'fingerprinting' and done >= 3:
            stop.set()

    with pytest.raises(ScanCancelled):
        run_scan([str(lib)], on_progress=progress, cancel=stop, **kw)
    plan = run_scan([str(lib)], **kw)
    assert plan['new_music']['first_scan'] is True          # nothing had completed before
    write_audio(f'{lib}/Artist/Later/01.flac', melody(77), FLAC)
    plan = run_scan([str(lib)], **kw)
    nm = plan['new_music']
    assert nm['first_scan'] is False and nm['new_tracks'] == 1
    assert [os.path.relpath(f['folder'], lib) for f in nm['folders']] == ['Artist/Later']


def test_damaged_file_is_fingerprinted_through_ffmpeg(library, tmp_path):
    from musicdedup.cache import Cache
    from musicdedup.fingerprint import run_fpcalc
    from musicdedup.matcher import find_matches
    from musicdedup.scanner import scan

    lib = tmp_path / 'lib'
    shutil.copytree(f'{library}/Artist/Album', lib / 'Album')
    os.makedirs(lib / 'Damaged copy')
    for name in sorted(os.listdir(lib / 'Album')):
        write_audio(str(lib / 'Damaged copy' / (name[:-5] + '.mp3')), melody(int(name[:2])), MP3)
    victim = lib / 'Damaged copy' / '02.mp3'
    data = bytearray(victim.read_bytes())
    mid = len(data) // 2
    data[mid:mid + 4000] = bytes((i * 37) % 256 for i in range(4000))
    victim.write_bytes(bytes(data))

    duration, fp, damaged = run_fpcalc(str(victim))
    assert damaged and 39 < duration < 41
    cache = Cache(str(tmp_path / 'c.db'))
    result = scan([str(lib)], cache)
    t = next(t for t in result.tracks if t.path.endswith('02.mp3'))
    assert t.usable and t.info.damaged and not t.error
    matches = find_matches(result.tracks)
    assert any(o.path.endswith('Album/02.flac') for o in matches.same[t])
    cache.close()
