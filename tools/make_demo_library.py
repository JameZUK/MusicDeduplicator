"""Build a fictional demo library, for screenshots and trying the tool out.

Every band, album and track name is invented; the music is synthesised (seeded, so
the same every time) and the covers are abstract art drawn by ffmpeg. It covers the
cases the dashboard shows: the same album in hi-res, CD quality and MP3; a standard
edition inside a deluxe; an explicit and a clean edit; a tag-stripped copy; an
incomplete copy; a corrupt file; a damaged file; an accidental copy inside a folder;
and a compilation sharing tracks with albums.

Usage:
    python tools/make_demo_library.py OUT_DIR            # the library, in OUT_DIR/Music
    python tools/make_demo_library.py OUT_DIR --later    # add "new music" for a second scan
    musicdedup serve OUT_DIR/plan.json --library OUT_DIR/Music --within-folders --move-to OUT_DIR/Quarantine

Needs ffmpeg, numpy and mutagen.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import wave

import numpy as np
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TRCK
from mutagen.mp3 import MP3

RATE = 48000


def song(seed: int, seconds: float = 80.0) -> np.ndarray:
    """A short 'song' with an intro, verses, a build, choruses, a breakdown and an outro."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    out = np.zeros(n)
    beat = 60 / rng.integers(92, 132)
    scale = np.array([0, 2, 3, 5, 7, 8, 10, 12])
    root = 110 * 2 ** (rng.integers(0, 12) / 12)
    pos = 0
    while pos < n:   # melody
        dur = int(beat * rng.choice([0.5, 1, 1, 2]) * RATE)
        f = root * 2 ** (rng.choice(scale) / 12) * rng.choice([1, 2])
        t = np.arange(min(dur, n - pos)) / RATE
        env = np.minimum(1, t * 30) * np.exp(-t * rng.uniform(1.5, 4))
        out[pos:pos + len(t)] += env * sum(np.sin(2 * np.pi * f * k * t) / k for k in (1, 2, 3)) * 0.35
        pos += dur
    for b in np.arange(0, seconds, beat):   # kick on the beat, hat off it
        i = int(b * RATE)
        k = np.arange(min(int(0.25 * RATE), n - i)) / RATE
        out[i:i + len(k)] += np.sin(2 * np.pi * (60 + 90 * np.exp(-k * 30)) * k) * np.exp(-k * 12) * 0.9
        j = int((b + beat / 2) * RATE)
        h = min(int(0.05 * RATE), max(0, n - j))
        out[j:j + h] += rng.normal(0, 0.15, h) * np.exp(-np.arange(h) / RATE * 80)
    gain = np.ones(n)
    for a, b, g in [(0, .08, .25), (.08, .30, .6), (.30, .40, .8), (.40, .62, 1.0), (.62, .72, .35),
                    (.72, .92, 1.0), (.92, 1.0, .2)]:
        gain[int(a * n):int(b * n)] = g
    out *= np.convolve(gain, np.ones(4800) / 4800, mode='same')
    return out / np.abs(out).max() * 0.9


class Builder:
    def __init__(self, out: str):
        self.lib = os.path.join(out, 'Music')
        self.tmp = tempfile.mkdtemp(prefix='musicdedup-demo-')

    def wav(self, key, samples=None, seed=None) -> str:
        path = os.path.join(self.tmp, f'{key}.wav')
        if not os.path.exists(path):
            samples = song(seed) if samples is None else samples
            with wave.open(path, 'wb') as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes((np.stack([samples, np.roll(samples, 40)], axis=1) * 32000).astype('<i2').tobytes())
        return path

    @staticmethod
    def encode(wav: str, dst: str, kind: str) -> None:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        codec = {'hires': ['-c:a', 'flac', '-sample_fmt', 's32', '-ar', '96000'],
                 'cd': ['-c:a', 'flac', '-sample_fmt', 's16', '-ar', '44100'],
                 'mp3': ['-c:a', 'libmp3lame', '-b:a', '320k', '-ar', '44100']}[kind]
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', wav, *codec, dst], check=True)

    @staticmethod
    def tag(path, artist, album, title, track):
        if path.endswith('.flac'):
            f = FLAC(path)
            f.update({'artist': artist, 'album': album, 'title': title, 'tracknumber': str(track)})
        else:
            f = MP3(path, ID3=ID3)
            if f.tags is None:
                f.add_tags()
            for frame in (TPE1(encoding=3, text=artist), TALB(encoding=3, text=album),
                          TIT2(encoding=3, text=title), TRCK(encoding=3, text=str(track))):
                f.tags.add(frame)
        f.save()

    @staticmethod
    def cover(folder, style):
        os.makedirs(folder, exist_ok=True)
        src = {
            'mandel': 'mandelbrot=s=600x600:start_scale=0.012:start_x=-0.7436:start_y=0.1318:maxiter=600,hue=h=30',
            'cells': 'cellauto=s=600x600:rule=110:random_fill_ratio=0.5,scale=600:600,hue=h=200:s=4',
            'life': 'life=s=150x150:mold=25:life_color=#f2a93b:death_color=#1a1408:mold_color=#7a3b1d,'
                    'scale=600:600:flags=neighbor',
            'grad': 'gradients=s=600x600:c0=0x0b3d4f:c1=0xe7735a:c2=0xf2d16b:x0=0:y0=0:x1=600:y1=600:nb_colors=3',
            'grad2': 'gradients=s=600x600:c0=0x1d1a2f:c1=0x7fc8a0:x0=300:y0=0:x1=300:y1=600:type=radial',
            'mandel2': 'mandelbrot=s=600x600:start_scale=0.3:start_x=-0.75:start_y=0:maxiter=200,hue=h=150:s=1.4',
            'grad3': 'gradients=s=600x600:c0=0x2b1055:c1=0xd16ba5:c2=0x86a8e7:x0=0:y0=600:x1=600:y1=0:nb_colors=3',
            'cells2': 'cellauto=s=600x600:rule=30:random_fill_ratio=0.4,scale=600:600,hue=h=40:s=3',
        }[style]
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', src, '-frames:v', '1',
                        '-vf', 'vignette=PI/5,noise=alls=6:allf=t', os.path.join(folder, 'cover.jpg')], check=True)

    def album(self, artist, title, songs, copies, art):
        """songs: [(seed, title)]; copies: [(folder relative to the library, kind)]."""
        for folder, kind in copies:
            d = os.path.join(self.lib, folder)
            if kind != 'mp3':
                self.cover(d, art)
            for i, (seed, name) in enumerate(songs, 1):
                dst = os.path.join(d, f"{i:02d} {name}.{'mp3' if kind == 'mp3' else 'flac'}")
                self.encode(self.wav(seed, seed=seed), dst, kind)
                self.tag(dst, artist, title, name, i)

    def done(self):
        shutil.rmtree(self.tmp)


def build(b: Builder) -> None:
    ag = [(11, 'Signal Fires'), (12, 'Glass Arcade'), (13, 'Night Bus to Halden'), (14, 'Afterglow Transit'),
          (15, 'Paper Satellites'), (16, 'Slow Weather')]
    b.album('Neon Harbour', 'Afterglow Transit', ag, [
        ('Neon Harbour/Afterglow Transit [24-96]', 'hires'),
        ('Neon Harbour/Afterglow Transit (CD rip)', 'cd'),
        ('Downloads/Neon Harbour - Afterglow Transit', 'mp3')], 'mandel')

    qm = [(21, 'Wire and Bone'), (22, 'Second Hand Light'), (23, 'Quiet Machinery'), (24, 'The Long Room'),
          (25, 'Thistle'), (26, 'Northbound')]
    bonus = [(27, 'Wire and Bone (Demo)'), (28, 'Lanterns'), (29, 'Static Hymn')]
    b.album('The Paper Moths', 'Quiet Machinery', qm, [('The Paper Moths/Quiet Machinery', 'cd')], 'cells')
    b.album('The Paper Moths', 'Quiet Machinery (Deluxe Edition)', qm + bonus,
            [('The Paper Moths/Quiet Machinery (Deluxe Edition)', 'hires')], 'cells')

    lt = [(31, 'Low Tide Signals'), (32, 'Saltwork'), (33, 'Harbour Lights'), (34, 'Undertow'), (35, 'Gull Choir')]
    b.album('Juniper Static', 'Low Tide Signals', lt, [('Juniper Static/Low Tide Signals', 'cd')], 'grad')
    b.album('Juniper Static', 'Low Tide Signals', lt[:4], [('Juniper Static/Low Tide Signals (2019)', 'cd')], 'grad')
    d = os.path.join(b.lib, 'Unsorted/Album 07')        # tags stripped and renamed: only the audio matches
    for i, (seed, _) in enumerate(lt, 1):
        b.encode(b.wav(seed, seed=seed), os.path.join(d, f'track{i:02d}.flac'), 'cd')

    fw = [(41, 'Ferris Wheel Summer'), (42, 'Postcards'), (43, 'Lido'), (44, 'Sunburn Radio'),
          (45, 'Last Train Home')]
    b.album('Marlow & the Long Weekend', 'Ferris Wheel Summer', fw,
            [('Marlow & the Long Weekend/Ferris Wheel Summer', 'hires'),
             ('Marlow & the Long Weekend/Ferris Wheel Summer (copy)', 'cd')], 'life')
    with open(os.path.join(b.lib, 'Marlow & the Long Weekend/Ferris Wheel Summer (copy)/06 Bonus.flac'), 'wb') as f:
        f.write(b'fLaC' + os.urandom(4000))              # corrupt: that folder is never removed
    shutil.copy2(os.path.join(b.lib, 'Marlow & the Long Weekend/Ferris Wheel Summer/03 Lido.flac'),
                 os.path.join(b.lib, 'Marlow & the Long Weekend/Ferris Wheel Summer/03 Lido (1).flac'))

    ex = [(51, 'Copper Teeth'), (52, 'Bad Language'), (53, 'Grey Matter'), (54, 'Halfway Gone')]
    b.album('Vesper Lane', 'Copper Teeth', ex, [('Vesper Lane/Copper Teeth [Explicit]', 'hires')], 'grad2')
    clean = song(52)
    clean[int(31 * RATE):int(33 * RATE)] *= 0.02           # the "censored" line
    dc = os.path.join(b.lib, 'Vesper Lane/Copper Teeth [Clean]')
    b.cover(dc, 'grad2')
    for i, (seed, name) in enumerate(ex, 1):
        dst = os.path.join(dc, f'{i:02d} {name}.flac')
        b.encode(b.wav('clean52', samples=clean) if seed == 52 else b.wav(seed, seed=seed), dst, 'cd')
        b.tag(dst, 'Vesper Lane', 'Copper Teeth', name, i)

    hd = [(71, 'Orbital Hymns'), (72, 'Glasshouse'), (73, 'Weightless'), (74, 'Kite Season')]
    b.album('Hollow Dunes', 'Orbital Hymns', hd, [('Hollow Dunes/Orbital Hymns', 'hires')], 'grad3')
    b.album('Hollow Dunes', 'Orbital Hymns', hd, [('Downloads/Hollow Dunes - Orbital Hymns', 'mp3')], 'grad3')
    mp3 = os.path.join(b.lib, 'Downloads/Hollow Dunes - Orbital Hymns/02 Glasshouse.mp3')
    data = bytearray(open(mp3, 'rb').read())                # a damaged frame: playable, flagged
    data[len(data) // 2:len(data) // 2 + 3000] = bytes((i * 37) % 256 for i in range(3000))
    open(mp3, 'wb').write(bytes(data))

    comp = [(13, 'Night Bus to Halden'), (33, 'Harbour Lights'), (43, 'Lido'), (61, 'Cassette Ghosts')]
    b.album('Various Artists', 'Late Night Drives', comp, [('Various Artists/Late Night Drives', 'cd')], 'mandel2')


def later(b: Builder) -> None:
    """Music 'added since the last scan', so the dashboard has new music to show."""
    gs = [(81, 'Greyhound Summer'), (82, 'Ferry Lights'), (83, 'Copper Coast')]
    b.album('Ash Atlas', 'Greyhound Summer', gs, [('Ash Atlas/Greyhound Summer', 'cd')], 'cells2')


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('out')
    p.add_argument('--later', action='store_true', help="add new music for a second scan")
    args = p.parse_args()
    b = Builder(args.out)
    try:
        (later if args.later else build)(b)
    finally:
        b.done()
    # Where the dashboard moves removed copies (it must exist before `serve` starts).
    os.makedirs(os.path.join(args.out, 'Quarantine'), exist_ok=True)
    print('demo library at', b.lib)


if __name__ == '__main__':
    main()
