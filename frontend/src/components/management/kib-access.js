/**
 * Who sees Kib's Configuration tab (SET-04). The sidebar hides "AI" from people who may not
 * change it, but Spotlight, the search widget and "Ask Kib about this" open the page: such a
 * person then saw every control, live, and each change answered with an error. They now get
 * Ask Kib and AI search only. The rights are the ones the settings route asks for.
 */
import { currentUser, hasScope } from '../../route-access.js';

const MANAGE = ['system:config', 'storage:admin'];
const CONFIG_PANE = 'mgmt-pane-ai-index';

/**
 * True for a person who may change Kib's settings; also before anyone is known.
 * @param {{scopes?: string[]} | null} [user]
 */
export function mayManageKib(user = currentUser()) {
  return !user || MANAGE.some((s) => hasScope(user.scopes, s));
}

/**
 * Hides the Configuration tab and its pane from a person who may not change Kib.
 * @param {string} paneId the pane that is being opened
 * @param {{scopes?: string[]} | null} [user]
 * @returns {string} the pane to show: Ask Kib where Configuration was asked for and is not theirs
 */
export function kibPaneFor(paneId, user = currentUser()) {
  const may = mayManageKib(user);
  for (const id of ['mgmt-tab-ai-index', CONFIG_PANE]) {
    const el = document.getElementById(id);
    if (!el) continue;
    if (may) el.removeAttribute('hidden');
    else el.setAttribute('hidden', '');
  }
  return !may && paneId === CONFIG_PANE ? 'mgmt-pane-ai-chat' : paneId;
}

/**
 * The cards that load with a Kib tab: each person's own Immich with AI search; "AI for apps" and
 * the AI pack with Configuration.
 * @param {string} paneId
 * @param {{scopes?: string[]} | null} [user]
 */
export function loadKibExtras(paneId, user = currentUser()) {
  const isAdmin = Boolean(user) && hasScope(user.scopes, 'system:config');
  if (paneId === 'mgmt-pane-ai-rag' || paneId === 'mgmt-pane-ai-visual') {
    import('../immich-settings.js')
      .then((m) => m.renderImmichSettings(document.getElementById('immich-settings-mount'), isAdmin))
      .catch(() => {});
  }
  if (paneId === CONFIG_PANE) {
    import('../ai-apps-settings.js').then((m) => m.renderAiApps(document.getElementById('ai-apps-mount'), isAdmin)).catch(() => {}); // COMP-07
    import('../ai-pack-settings.js').then((m) => m.renderAiPack(document.getElementById('ai-pack-mount'), isAdmin)).catch(() => {}); // AI-40
  }
}
