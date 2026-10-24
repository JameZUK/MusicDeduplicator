// Hash routing: #/overview, #/review, #/review/12?copy=.., #/history. Any view can carry
// ?a=..&b=.. to show the comparison panel over it (old #/compare links open over Overview).

function parse() {
  const raw = location.hash.replace(/^#\/?/, '') || 'overview';
  const [path, query = ''] = raw.split('?');
  const [view, id] = path.split('/');
  return { view: view === 'compare' ? 'overview' : view, id: id ?? null,
           query: Object.fromEntries(new URLSearchParams(query)) };
}

export const route = $state(parse());

addEventListener('hashchange', () => Object.assign(route, parse()));

export function go(view, id = null, query = null) {
  let hash = `#/${view}${id !== null ? `/${id}` : ''}`;
  const q = query && Object.fromEntries(Object.entries(query).filter(([, v]) => v !== null && v !== undefined && v !== ''));
  if (q && Object.keys(q).length) hash += `?${new URLSearchParams(q)}`;
  location.hash = hash;
}

/** Changes the query of the current view (null removes a key). */
export function setQuery(patch) {
  go(route.view, route.id, { ...route.query, ...patch });
}

/** Opens the comparison panel over whatever is on screen. */
export const openCompare = (a, b) => setQuery({ a, b });
export const closeCompare = () => setQuery({ a: null, b: null });
