/**
 * Ransomware guard and blocked addresses, in Security (M4, M5).
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast } from '../toast.js';
import { formatDateTime } from '../format.js';

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  children.flat().forEach((c) => c && n.append(c));
  return n;
}

function toggle(label, checked, onChange) {
  const input = el('input', { type: 'checkbox' });
  input.checked = Boolean(checked);
  input.addEventListener('change', () => onChange(input.checked));
  return el('label', { class: 'guard-toggle' }, input, el('span', { text: label }));
}

async function save(changes) {
  try {
    await api.put('/api/security/ransomware', changes);
    showToast(t('guard.saved', 'Ransomware guard settings saved'), 'success');
  } catch (err) {
    showToast(t('guard.save_failed', 'Could not save: {error}', { error: err.message }), 'error');
  }
  renderGuardPanel();
}

export async function renderGuardPanel() {
  const host = document.getElementById('sec-guard-card');
  if (!host) return;
  let st;
  let blocks = [];
  try {
    [st, blocks] = await Promise.all([api.get('/api/security/ransomware'), api.get('/api/security/ip-blocks')]);
  } catch (err) {
    host.replaceChildren(el('div', { class: 'guard-muted', text: t('guard.load_failed', 'Could not load the ransomware guard: {error}', { error: err.message }) }));
    return;
  }
  const parts = [el('div', { class: 'guard-title', text: t('guard.title', '🛡️ Ransomware guard') })];
  if (st.frozen) {
    parts.push(
      el('div', { class: 'guard-alert', role: 'alert' },
        el('strong', { text: t('guard.frozen', 'Writes are frozen.') }),
        ' ',
        t('guard.frozen_reason', '{reason} ({when}). Source: {user} from {ip}.', {
          reason: st.reason || '',
          when: st.frozen_at ? formatDateTime(st.frozen_at * 1000) : '',
          user: st.source?.user || '-',
          ip: st.source?.ip || '-',
        }),
        el('button', {
          class: 'btn-pill-toggle guard-unfreeze',
          text: t('guard.unfreeze', 'Lift the freeze'),
          onclick: async () => {
            if (!window.confirm(t('guard.unfreeze_confirm', 'Only lift the freeze after the computer that made the changes is cleaned up. Continue?'))) return;
            await api.post('/api/security/ransomware/unfreeze', {});
            showToast(t('guard.unfrozen', 'Writes are allowed again'), 'success');
            renderGuardPanel();
          },
        })
      )
    );
  }
  parts.push(
    el('div', { class: 'guard-muted', text: t('guard.desc', 'Stops all writes, snapshots pools that support it, blocks the address and alerts you when files are renamed or deleted en masse, renamed to ransomware extensions, or a guard file changes.') }),
    toggle(t('guard.enabled', 'Watch for ransomware'), st.enabled, (v) => save({ enabled: v })),
    toggle(
      t('guard.canaries', 'Place guard files in shares ({count} placed). Catches attacks over SMB and NFS too.', { count: st.canary_count || 0 }),
      st.canaries,
      (v) => save({ canaries: v })
    ),
    el('div', { class: 'guard-title guard-sub', text: t('guard.blocked_title', 'Blocked addresses') })
  );
  if (!blocks.length) {
    parts.push(el('div', { class: 'guard-muted', text: t('guard.none_blocked', 'None. Addresses with 20 failed sign-ins in 15 minutes are blocked for an hour.') }));
  } else {
    const list = el('ul', { class: 'guard-blocks' });
    blocks.forEach((b) => {
      list.append(
        el('li', {},
          el('code', { text: b.ip }),
          el('span', { class: 'guard-muted', text: ` ${b.reason || ''}${b.until ? ` · ${t('guard.until', 'until {when}', { when: formatDateTime(b.until * 1000) })}` : ''}` }),
          el('button', {
            class: 'btn-pill-toggle',
            text: t('guard.unblock', 'Unblock'),
            'aria-label': t('guard.unblock_ip', 'Unblock {ip}', { ip: b.ip }),
            onclick: async () => {
              await api.delete(`/api/security/ip-blocks/${encodeURIComponent(b.ip)}`);
              renderGuardPanel();
            },
          })
        )
      );
    });
    parts.push(list);
  }
  host.replaceChildren(...parts);
}
