// Thin client for the musicdedup server. Writes carry the session's CSRF token.

let csrf = '';

async function request(method, path, body) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
  const res = await fetch(`./api/${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

export async function loadSession() {
  const s = await request('GET', 'session');
  csrf = s.csrf;
  return s;
}

export const api = {
  plan: () => request('GET', 'plan'),
  group: (id) => request('GET', `group/${id}`),
  folder: (path) => request('GET', `folder?path=${encodeURIComponent(path)}`),
  waveform: (path) => request('GET', `waveform?path=${encodeURIComponent(path)}`),
  compare: (a, b) => request('GET', `compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
  decisions: () => request('GET', 'decisions'),
  saveDecisions: (d) => request('PUT', 'decisions', d),
  preview: (decisions) => request('POST', 'preview', { decisions }),
  apply: (body) => request('POST', 'apply', body),
  undo: (journal) => request('POST', 'undo', { journal }),
  job: (id) => request('GET', `jobs/${id}`),
  history: () => request('GET', 'history'),
  scanState: () => request('GET', 'scan'),
  scans: () => request('GET', 'scans'),
  startScan: () => request('POST', 'scan', {}),
  stopScan: () => request('POST', 'scan/cancel', {}),
};

export const audioUrl = (path) => `./api/audio?path=${encodeURIComponent(path)}`;
export const coverUrl = (folder) => `./api/cover?folder=${encodeURIComponent(folder)}`;
