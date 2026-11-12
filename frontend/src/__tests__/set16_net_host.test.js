/** SET-16, decision D2: the network page follows what the host lets Kiboto change. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { READ_ONLY, applyNetCaps, canChange, hostNote, netCaps, portPayload, setNetCaps } from '../components/management/net-host.js';
import { openNetworkPortModal, saveNetworkPortConfig } from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

const UNRAID = { managed: false, where: 'unraid', can_change: { address: false, mtu: false, speed: false, wake_on_lan: false, bond: false, bridge: false, vlan: false } };
const MANAGED = { managed: true, where: 'system', can_change: { address: true, mtu: true, speed: true, wake_on_lan: true, bond: true, bridge: true, vlan: true } };

describe('net-host', () => {
  beforeEach(() => setNetCaps(null));

  it('starts read-only and ignores rubbish', () => {
    expect(netCaps()).toBe(READ_ONLY);
    setNetCaps('nope');
    expect(netCaps()).toBe(READ_ONLY);
    expect(canChange('mtu')).toBe(false);
  });

  it('says where to change it, with a fallback for an unknown host', () => {
    expect(hostNote(UNRAID)).toBe('This is set up in Unraid, under Settings → Network Settings. Kiboto shows it but does not change it.');
    expect(hostNote({ where: 'mars' })).toContain("the host system's own network settings");
    for (const where of ['truenas', 'proxmox', 'ugos']) expect(hostNote({ where })).not.toContain('host system');
  });

  it('marks fields read-only, hides edit buttons and shows the note', () => {
    document.body.innerHTML = `
      <input id="mtu" data-net-setting="mtu"><div data-net-setting="bond" id="box"><input type="checkbox" id="slave"></div>
      <button id="apply" data-net-edit="address">Apply</button>
      <p class="net-host-note" data-net-for="mtu speed" id="note" hidden></p>
      <p class="net-host-note" data-net-for="" id="empty" hidden></p>`;
    applyNetCaps(document, UNRAID);
    expect(document.getElementById('mtu').disabled).toBe(true);
    expect(document.getElementById('slave').disabled).toBe(true);
    expect(document.getElementById('box').classList.contains('is-readonly')).toBe(true);
    expect(document.getElementById('apply').style.display).toBe('none');
    expect(document.getElementById('note').hidden).toBe(false);
    expect(document.getElementById('note').textContent).toContain('Unraid');
    expect(document.getElementById('empty').hidden).toBe(true);
    applyNetCaps(document, MANAGED);
    expect(document.getElementById('mtu').disabled).toBe(false);
    expect(document.getElementById('apply').style.display).toBe('');
    expect(document.getElementById('note').hidden).toBe(true);
  });

  it('sends the nickname always and the wiring only where allowed', () => {
    const v = { alias: 'Uplink', mtu: 9000, wol_enabled: true, autoneg: false, speed: 1000 };
    expect(portPayload(v, UNRAID)).toEqual({ alias: 'Uplink' });
    expect(portPayload(v, MANAGED)).toEqual({ alias: 'Uplink', mtu: 9000, wol_enabled: true, autoneg: false, speed: 1000, duplex: 'full' });
  });
});

describe('the port dialog on a host Kiboto does not manage', () => {
  it('saves only the nickname, says where the rest is, and labels the button so', async () => {
    document.body.innerHTML = `
      <div id="network-port-config-overlay" style="display:none">
        <span id="net-port-cfg-iface"></span><span id="net-port-cfg-dot"></span>
        <input id="net-port-alias-input">
        <button class="net-mtu-preset" data-net-setting="mtu" data-mtu="1500"></button>
        <input id="net-port-mtu-input" data-net-setting="mtu" value="1500">
        <input type="checkbox" id="net-port-wol-toggle" data-net-setting="wake_on_lan">
        <span id="net-port-wol-desc"></span>
        <select id="net-port-speed-select" data-net-setting="speed"><option value="auto">auto</option></select>
        <span id="net-port-ro-mac"></span><span id="net-port-ro-driver"></span><span id="net-port-ro-pci"></span><span id="net-port-ro-link"></span>
        <p class="net-host-note" data-net-for="mtu speed wake_on_lan" hidden></p>
        <button id="net-port-cfg-save-btn"></button>
      </div>`;
    setNetCaps(UNRAID);
    vi.spyOn(api, 'get').mockResolvedValueOnce({ status: 'ok', interface: { name: 'eth0', is_up: true }, alias: '', mtu: 1500, wol_supported: true, autoneg: true });
    await openNetworkPortModal('eth0');
    expect(document.getElementById('net-port-mtu-input').disabled).toBe(true);
    expect(document.getElementById('net-port-cfg-save-btn').textContent).toBe('Save nickname');
    expect(document.querySelector('.net-host-note').textContent).toContain('Unraid');
    document.getElementById('net-port-alias-input').value = ' Uplink ';
    document.getElementById('net-port-mtu-input').value = 'not a number'; // ignored: not changeable here
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'ok', alias: 'Uplink' });
    vi.spyOn(api, 'get').mockResolvedValue({ status: 'ok' });
    vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    await saveNetworkPortConfig();
    expect(post).toHaveBeenCalledWith('/api/network/port/eth0', { alias: 'Uplink' });
    expect(document.getElementById('net-port-cfg-save-btn').textContent).toBe('Save nickname');
    vi.restoreAllMocks();
  });
});
