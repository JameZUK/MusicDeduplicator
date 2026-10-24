export function bytes(n) {
  if (!n) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i < 2 ? 0 : 1)} ${units[i]}`;
}

export function time(seconds) {
  if (!Number.isFinite(seconds)) return '0:00';
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function rel(path, roots) {
  for (const r of roots || []) {
    if (path === r) return '.';
    if (path.startsWith(r.replace(/\/$/, '') + '/')) return path.slice(r.replace(/\/$/, '').length + 1);
  }
  return path;
}

export const base = (p) => p.split('/').pop();
export const dir = (p) => p.slice(0, p.lastIndexOf('/'));

/** Splits "Artist/Album" style relative folder paths into artist and album. */
export function artistAlbum(relPath) {
  const parts = relPath.split('/');
  if (parts.length === 1) return { artist: '', album: parts[0] };
  const disc = /^\s*(cd|disc|disk)\s*\d+\s*$/i.test(parts.at(-1));
  const album = disc ? `${parts.at(-2)} · ${parts.at(-1)}` : parts.at(-1);
  // The folder holding the album is the artist; anything above it (e.g. "Organised") is
  // just where the library keeps it.
  const artist = parts.at(disc ? -3 : -2) || '';
  return { artist, album };
}

export function when(iso) {
  const d = new Date(iso.replace(/([+-]\d{2})(\d{2})$/, '$1:$2'));
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
