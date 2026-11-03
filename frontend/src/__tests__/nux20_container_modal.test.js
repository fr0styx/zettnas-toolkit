/** NUX-20: the container details window reads in the person's language. */
import { describe, it, expect, beforeAll, afterAll, beforeEach, vi } from 'vitest';
import { setLanguage } from '../i18n.js';
import { api } from '../api.js';
import {
  initContainerModal,
  openContainerInspector,
  switchContainerTab,
  openContainerDeleteModal,
  _resetContainerModalForTesting,
} from '../components/container-modal.js';

const HOSTED = {
  cid: 'c1',
  overview: { id: 'c1', full_id: 'c1full', name: 'pihole', image: 'pihole/pihole:2026.10', state: 'running', running: true, network_mode: 'host', restart_policy: 'always' },
  resources: {},
  primary_port: 80,
  webui_url: 'http://[HOST]:80/',
  ports: [{ public_port: 80, private_port: 80, type: 'tcp', ip: 'host', is_host_network: true }],
  mounts: [],
  env: [],
};

const BRIDGED = {
  ...HOSTED,
  overview: { ...HOSTED.overview, name: 'paperless', network_mode: 'bridge' },
  ports: [{ public_port: 8000, private_port: 8000, type: 'tcp', ip: '0.0.0.0' }],
  env: [{ key: 'A', value: '1', masked_value: '1', is_secret: false }, { key: 'B', value: 'x', masked_value: '••', is_secret: true }],
};

describe('container details in German (NUX-20)', () => {
  beforeAll(async () => { await setLanguage('de'); });
  afterAll(async () => { await setLanguage('en'); });
  beforeEach(() => { _resetContainerModalForTesting(); vi.restoreAllMocks(); });

  it('names the tabs, the log lengths and the terminal keys', () => {
    initContainerModal();
    const tabs = [...document.querySelectorAll('.ci-tab-btn')].map((b) => b.textContent.trim());
    expect(tabs).toEqual(['📊 Übersicht', '🌐 Ports & Web', '📁 Ordner & Speicher', '🔑 Umgebung', '📜 Docker Compose', '📄 Live-Protokoll', '💻 Terminal', '✏️ Container bearbeiten']);
    expect(document.querySelector('.ci-tab-btn [aria-hidden="true"]').textContent).toBe('📊');
    const lines = [...document.querySelectorAll('#ci-logs-tail-select option')].map((o) => o.textContent);
    expect(lines).toEqual(['Letzte 50 Zeilen', 'Letzte 100 Zeilen', 'Letzte 200 Zeilen', 'Letzte 500 Zeilen', 'Letzte 1000 Zeilen']);
    expect(document.querySelector('#ci-logs-tail-select').value).toBe('200');
    expect([...document.querySelectorAll('[data-cmd]')].map((b) => b.dataset.cmd)).toEqual(['ls -la', 'ps aux', 'df -h']);
    expect(document.getElementById('ci-term-send-btn').textContent).toBe('Ausführen');
  });

  it('explains host networking and shows the overview', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => (url.includes('/details') ? HOSTED : {}));
    await openContainerInspector('c1', 'pihole');
    const overview = document.getElementById('ci-overview-content').textContent;
    expect(overview).toContain('Status & Laufzeit');
    expect(overview).toContain('Modus: host');
    expect(overview).toContain('Neustartregel');
    expect(overview).toContain('Gefahrenbereich');
    const ports = document.getElementById('ci-ports-content').textContent;
    expect(ports).toContain('Host-Netzwerkmodus');
    expect(ports).toContain('Auf Port 80 (Host-Netzwerk)');
    expect(ports).toContain('Host direkt (:80)');
    expect(ports).toContain('Host-Netzwerk aktiv');
    expect(document.getElementById('ci-mounts-content').textContent).toContain('In diesem Container sind keine Ordner eingebunden.');
    expect(document.getElementById('ci-env-content').textContent).toContain('Keine eigenen Umgebungsvariablen.');
  });

  it('counts variables, checks ports and edits in German', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/details')) return BRIDGED;
      if (url.includes('check_port')) return { available: false, in_use_by: 'traefik' };
      return {};
    });
    await openContainerInspector('c1', 'paperless');
    expect(document.getElementById('ci-env-stats').textContent).toBe('2 Variablen (1 verborgen)');
    await switchContainerTab('ports');
    const input = document.querySelector('.ci-port-input');
    input.value = '8080';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const status = document.getElementById('ci-port-check-0');
    await vi.waitFor(() => expect(status.textContent).toContain('Port 8080 ist belegt von traefik'));
    input.value = '0';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    expect(status.textContent).toBe('Ungültiger Port');

    await switchContainerTab('edit');
    const form = document.getElementById('cie-form-host').textContent;
    expect(form).toContain('Container-Einstellungen');
    expect(form).toContain('Port-Zuordnungen');
    expect(form).toContain('Sicherungs-Container behalten (der alte bleibt als {name}.backup)');
    expect(document.getElementById('cie-btn-cancel').textContent).toBe('Abbrechen');
    expect(get).toHaveBeenCalled();
  });

  it('says when details, logs or the compose file could not be read', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('weg'));
    await openContainerInspector('c1', 'paperless');
    expect(document.getElementById('ci-overview-loading').textContent).toBe('Container-Details konnten nicht geladen werden: weg');
    await switchContainerTab('logs');
    await vi.waitFor(() => expect(document.getElementById('ci-logs-terminal').textContent).toBe('Protokoll konnte nicht gelesen werden: weg'));
    await switchContainerTab('compose');
    await vi.waitFor(() => expect(document.getElementById('ci-compose-code').textContent).toBe('# Compose-Datei konnte nicht erstellt werden: weg'));
  });

  it('asks before deleting a container', () => {
    openContainerDeleteModal('c1abcdef123456', 'paperless', 'paperless-ngx:2');
    const dialog = document.getElementById('container-delete-modal-overlay');
    expect(dialog.textContent).toContain('Den Container paperless (c1abcdef1234) endgültig löschen?');
    expect(dialog.textContent).toContain('Auch das Container-Image löschen (paperless-ngx:2)');
    expect(document.getElementById('cdm-cancel-btn').textContent).toBe('Abbrechen');
  });
});
