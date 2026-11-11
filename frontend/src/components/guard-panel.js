/**
 * Ransomware guard and blocked addresses, in Security (M4, M5).
 */
import { api } from '../api.js';
import { t } from '../i18n.js';
import { showToast, showDangerConfirm } from '../toast.js';
import { formatDateTime } from '../format.js';
import { setIconLabel } from '../ui/primitives.js';

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
  return el('label', { class: 'kb-toggle' }, input, el('span', { text: label }));
}

/** Turning a protection off asks first; turning it on does not (SET-14, Settings finding 23). */
function saveOrAsk(changes, turningOff, title, question) {
  if (!turningOff) return save(changes);
  showDangerConfirm(title, question, () => save(changes), () => renderGuardPanel());
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
  let blocks;
  try {
    [st, blocks] = await Promise.all([api.get('/api/security/ransomware'), api.get('/api/security/ip-blocks')]);
  } catch (err) {
    host.replaceChildren(el('div', { class: 'kb-muted', text: t('guard.load_failed', 'Could not load the ransomware guard: {error}', { error: err.message }) }));
    return;
  }
  const title = el('div', { class: 'kb-title' });
  setIconLabel(title, '🛡️', t('guard.title', 'Ransomware guard'));
  const parts = [title];
  if (st.frozen) {
    parts.push(
      el('div', { class: 'kb-alert kb-alert--danger', role: 'alert' },
        el('strong', { text: t('guard.frozen', 'Writes are frozen.') }),
        ' ',
        t('guard.frozen_reason', '{reason} ({when}). Source: {user} from {ip}.', {
          reason: st.reason || '',
          when: st.frozen_at ? formatDateTime(st.frozen_at * 1000) : '',
          user: st.source?.user || '-',
          ip: st.source?.ip || '-',
        }),
        el('button', {
          class: 'btn-pill-toggle kb-push-end',
          text: t('guard.unfreeze', 'Lift the freeze'),
          onclick: () => {
            // the app's own dialog, not the browser's (SET-14)
            showDangerConfirm(t('guard.unfreeze', 'Lift the freeze'), t('guard.unfreeze_confirm', 'Only lift the freeze after the computer that made the changes is cleaned up. Continue?'), async () => {
              try {
                await api.post('/api/security/ransomware/unfreeze', {});
                showToast(t('guard.unfrozen', 'Writes are allowed again'), 'success');
              } catch (err) {
                showToast(t('guard.unfreeze_failed', 'The freeze was not lifted: {error}', { error: err.message }), 'error');
              }
              renderGuardPanel();
            });
          },
        })
      )
    );
  }
  parts.push(
    el('div', { class: 'kb-muted', text: t('guard.desc', 'Stops all writes, snapshots pools that support it, blocks the address and alerts you when files are renamed or deleted en masse, renamed to ransomware extensions, or a guard file changes.') }),
    toggle(t('guard.enabled', 'Watch for ransomware'), st.enabled, (v) =>
      saveOrAsk({ enabled: v }, !v, t('guard.off_title', 'Turn off the ransomware guard?'),
        t('guard.off_q', 'Kiboto stops watching for mass renames and deletes, and nothing freezes writes during an attack.'))),
    toggle(
      t('guard.canaries', 'Place guard files in shares ({count} placed). Catches attacks over SMB and NFS too.', { count: st.canary_count || 0 }),
      st.canaries,
      (v) => saveOrAsk({ canaries: v }, !v, t('guard.canaries_off_title', 'Remove the guard files?'),
        t('guard.canaries_off_q', 'Attacks over SMB and NFS are then no longer noticed by the guard.'))
    ),
    el('div', { class: 'kb-title kb-title--sub', text: t('guard.blocked_title', 'Blocked addresses') })
  );
  if (!blocks.length) {
    parts.push(el('div', { class: 'kb-muted', text: t('guard.none_blocked', 'None. Addresses with 20 failed sign-ins in 15 minutes are blocked for an hour.') }));
  } else {
    const list = el('ul', { class: 'kb-list' });
    blocks.forEach((b) => {
      list.append(
        el('li', {},
          el('code', { text: b.ip }),
          el('span', { class: 'kb-muted', text: ` ${b.reason || ''}${b.until ? ` · ${t('guard.until', 'until {when}', { when: formatDateTime(b.until * 1000) })}` : ''}` }),
          el('button', {
            class: 'btn-pill-toggle',
            text: t('guard.unblock', 'Unblock'),
            'aria-label': t('guard.unblock_ip', 'Unblock {ip}', { ip: b.ip }),
            onclick: async () => {
              try {
                await api.delete(`/api/security/ip-blocks/${encodeURIComponent(b.ip)}`);
                showToast(t('guard.unblocked', '{ip} can sign in again', { ip: b.ip }), 'success');
              } catch (err) {
                showToast(t('guard.unblock_failed', '{ip} is still blocked: {error}', { ip: b.ip, error: err.message }), 'error');
              }
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
