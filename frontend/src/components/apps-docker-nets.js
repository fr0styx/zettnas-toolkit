// Apps window: "For experts: Docker networks", folded (moved from Network's Docker tab, SET-24).
// The cards come from the same layout read as the Network page, so network.js renders them; the
// create dialog is in Settings' markup, which is put in the page here when it isn't yet.
import { escapeHtml } from '../utils.js';
import { t } from '../i18n.js';

/** The folded group, closed: nothing is read until someone opens it. */
export function appsDockerNetsHtml() {
  return `<details class="apps-experts" id="apps-docker-nets">
    <summary>${escapeHtml(t('apps.experts_nets', 'For experts: Docker networks'))}</summary>
    <div class="apps-experts-head">
      <p class="apps-experts-desc">${escapeHtml(t('apps.experts_nets_desc', 'The networks your apps use to reach each other. Most apps need none of their own.'))}</p>
      <button type="button" class="btn-pill-toggle" id="btn-create-docker-net">${escapeHtml(t('net.create_docker_net', '+ Create Network'))}</button>
    </div>
    <div class="network-docker-list" id="network-docker-container"></div>
  </details>`;
}

const network = () => Promise.all([import('../management-dom.js').then((m) => m.ensureManagementDom()), import('./management/network.js')]).then(([, m]) => m);

/** Reads the networks when the group opens; the create button opens the dialog. Bound once.
 *  @param {ParentNode} [root] */
export function installAppsDockerNets(root = document) {
  const group = /** @type {HTMLElement | null} */ (root.querySelector('#apps-docker-nets'));
  if (!group || group.dataset.bound) return false;
  group.dataset.bound = '1';
  group.addEventListener('toggle', () => {
    if (/** @type {HTMLDetailsElement} */ (group).open) network().then((m) => m.fetchAndRenderNetworkTopology()).catch(() => {});
  });
  const create = group.querySelector('#btn-create-docker-net');
  if (create instanceof HTMLElement) {
    create.dataset.bound = '1'; // network.js binds this id too: one click, one dialog
    create.addEventListener('click', () => network().then((m) => m.openDockerNetworkCreateModal()).catch(() => {}));
  }
  return true;
}
