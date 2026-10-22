/**
 * Favorite folders for the File Explorer, kept per user on the server (/api/fs/favorites) so
 * they follow you to every browser. All explorer windows share this list and re-render on the
 * "fm:favorites" event.
 */
import { api } from '../api.js';
import { ZettEventBus } from '../event-bus.js';
import { showToast } from '../toast.js';
import { t } from '../i18n.js';

let _items = null;
let _loading = null;

const norm = (p) => String(p || '').replace(/\/+$/, '') || '/';

export function favorites() {
  return _items || [];
}

export function isFavorite(path) {
  const p = norm(path);
  return favorites().some((f) => f.path === p);
}

function set(items) {
  _items = (items || []).map((f) => ({ available: true, ...f }));
  ZettEventBus.emit('fm:favorites', _items);
  return _items;
}

export function loadFavorites(force = false) {
  if (_items && !force) return Promise.resolve(_items);
  if (!_loading) {
    _loading = api
      .get('/api/fs/favorites')
      .then((r) => set(r?.favorites))
      .catch(() => set(_items || []))
      .finally(() => {
        _loading = null;
      });
  }
  return _loading;
}

export async function addFavorite(path, name = '') {
  const p = norm(path);
  try {
    const r = await api.post('/api/fs/favorites', name ? { path: p, name } : { path: p });
    set(r?.favorites);
    showToast(t('fm.fav_added', 'Added {name} to Favorites', { name: name || p.split('/').pop() || p }), 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

export async function removeFavorite(path) {
  const p = norm(path);
  try {
    const r = await api.delete(`/api/fs/favorites?path=${encodeURIComponent(p)}`);
    set(r?.favorites);
    showToast(t('fm.fav_removed', 'Removed {name} from Favorites', { name: p.split('/').pop() || p }), 'info');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

export function toggleFavorite(path, name = '') {
  return isFavorite(path) ? removeFavorite(path) : addFavorite(path, name);
}

/** The location among `paths` that best matches where you are: the longest one containing it. */
export function closestPath(paths, current) {
  const here = norm(current);
  let best = null;
  for (const p of paths) {
    const n = norm(p);
    if ((here === n || here.startsWith(n === '/' ? '/' : n + '/')) && (!best || n.length > best.length)) best = n;
  }
  return best;
}
