// App-wide state. Decisions live on the server (so they survive reloads and are
// shared between devices); edits are saved shortly after they're made.
import { api } from './api.js';

export const store = $state({
  session: null,
  plan: null,
  decisions: { groups: {}, within: [] },
  saving: false,
  error: '',
  scan: { state: 'idle' },
});

let saveTimer;

export function decide(groupId, choice) {
  const key = String(groupId);
  if (choice === null) delete store.decisions.groups[key];
  else store.decisions.groups[key] = choice;
  queueSave();
}

export function toggleWithin(path, on) {
  const set = new Set(store.decisions.within);
  on ? set.add(path) : set.delete(path);
  store.decisions.within = [...set];
  queueSave();
}

function queueSave() {
  clearTimeout(saveTimer);
  store.saving = true;
  saveTimer = setTimeout(async () => {
    try {
      await api.saveDecisions($state.snapshot(store.decisions));
    } catch (e) {
      store.error = `Couldn't save decisions: ${e.message}`;
    } finally {
      store.saving = false;
    }
  }, 400);
}

export function decisionOf(group) {
  return store.decisions.groups[String(group.id)] ?? null;
}

export function decisionKind(group) {
  const d = decisionOf(group);
  if (d === null) return 'undecided';
  if (d === 'accept' || d === 'skip') return d;
  return d.keep === group.keep ? 'accept' : 'changed';
}

/** Bytes freed by the groups decided so far (accepted or with a new keeper). */
export function decidedBytes(plan) {
  if (!plan) return 0;
  return plan.groups.reduce((sum, g) => {
    const k = decisionKind(g);
    return k === 'accept' || k === 'changed' ? sum + g.bytes : sum;
  }, 0);
}
