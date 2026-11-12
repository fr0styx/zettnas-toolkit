import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  openHostIpConfigModal,
  closeHostIpConfigModal,
  applyHostIpConfig,
  initNetworkControls,
} from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('Host IP & DNS dialog (SET-16: no trial; only a host Kiboto manages takes the change)', () => {
  let container;

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement('div');
    container.innerHTML = `
      <div id="net-kpi-ip-card">
        <button id="btn-open-host-ip-modal"></button>
        <div id="net-kpi-ip">192.168.1.50</div>
        <div id="net-kpi-iface">Via br0</div>
      </div>

      <!-- Host IP Configuration Modal -->
      <div id="network-host-config-overlay" style="display: none;">
        <button class="net-proto-btn active" data-proto="static" id="net-proto-btn-static"></button>
        <button class="net-proto-btn" data-proto="dhcp" id="net-proto-btn-dhcp"></button>
        <select id="net-host-iface-select"></select>

        <div id="net-host-static-fields">
          <input id="net-host-ip-input" />
          <button class="net-cidr-preset" data-netmask="255.255.255.0" id="net-cidr-preset-24"></button>
          <button class="net-cidr-preset" data-netmask="255.255.0.0" id="net-cidr-preset-16"></button>
          <button class="net-cidr-preset" data-netmask="255.0.0.0" id="net-cidr-preset-8"></button>
          <input id="net-host-netmask-input" value="255.255.255.0" />
          <input id="net-host-gateway-input" />
        </div>

        <button class="net-dns-preset" data-dns1="1.1.1.1" data-dns2="1.0.0.1" id="net-dns-preset-cloudflare"></button>
        <button class="net-dns-preset" data-dns1="8.8.8.8" data-dns2="8.8.4.4" id="net-dns-preset-google"></button>
        <button class="net-dns-preset" data-dns1="9.9.9.9" data-dns2="149.112.112.112" id="net-dns-preset-quad9"></button>

        <input id="net-host-dns1-input" />
        <input id="net-host-dns2-input" />

        <button id="net-host-cfg-close-btn"></button>
        <button id="net-host-cfg-cancel-btn"></button>
        <button id="net-host-cfg-apply-btn"></button>
      </div>

    `;
    document.body.appendChild(container);
    initNetworkControls();
  });

  afterEach(() => {
    container?.remove();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  const mockHostConfig = {
    status: 'ok',
    mode: 'static',
    interface: 'br0',
    available_interfaces: ['br0', 'eth0', 'eth1'],
    ip_address: '192.168.1.50',
    netmask: '255.255.255.0',
    cidr: 24,
    gateway: '192.168.1.1',
    dns1: '192.168.1.1',
    dns2: '1.1.1.1',
    dns_servers: ['192.168.1.1', '1.1.1.1'],
  };

  it('opens Host IP modal and populates static IP, gateway, and DNS fields', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockHostConfig);

    await openHostIpConfigModal();

    const overlay = document.getElementById('network-host-config-overlay');
    expect(overlay.style.display).toBe('flex');
    expect(document.getElementById('net-host-ip-input').value).toBe('192.168.1.50');
    expect(document.getElementById('net-host-netmask-input').value).toBe('255.255.255.0');
    expect(document.getElementById('net-host-gateway-input').value).toBe('192.168.1.1');
    expect(document.getElementById('net-host-dns1-input').value).toBe('192.168.1.1');
    expect(document.getElementById('net-host-dns2-input').value).toBe('1.1.1.1');

    const ifaceSelect = document.getElementById('net-host-iface-select');
    expect(ifaceSelect.options.length).toBe(3);
    expect(ifaceSelect.value).toBe('br0');

    expect(document.getElementById('net-cidr-preset-24').classList.contains('active')).toBe(true);
  });

  it('switches between DHCP and Static IP mode and toggles static fields visibility', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockHostConfig);
    await openHostIpConfigModal();

    const btnDhcp = document.getElementById('net-proto-btn-dhcp');
    const btnStatic = document.getElementById('net-proto-btn-static');
    const staticFields = document.getElementById('net-host-static-fields');

    // Switch to DHCP
    btnDhcp.click();
    expect(btnDhcp.classList.contains('active')).toBe(true);
    expect(btnStatic.classList.contains('active')).toBe(false);
    expect(staticFields.style.opacity).toBe('0.4');
    expect(staticFields.style.pointerEvents).toBe('none');

    // Switch back to Static
    btnStatic.click();
    expect(btnStatic.classList.contains('active')).toBe(true);
    expect(btnDhcp.classList.contains('active')).toBe(false);
    expect(staticFields.style.opacity).toBe('1');
    expect(staticFields.style.pointerEvents).toBe('auto');
  });

  it('handles CIDR presets and DNS presets correctly', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockHostConfig);
    await openHostIpConfigModal();

    const preset16 = document.getElementById('net-cidr-preset-16');
    preset16.click();
    expect(document.getElementById('net-host-netmask-input').value).toBe('255.255.0.0');
    expect(preset16.classList.contains('active')).toBe(true);

    const cloudflareDns = document.getElementById('net-dns-preset-cloudflare');
    cloudflareDns.click();
    expect(document.getElementById('net-host-dns1-input').value).toBe('1.1.1.1');
    expect(document.getElementById('net-host-dns2-input').value).toBe('1.0.0.1');
    expect(cloudflareDns.classList.contains('active')).toBe(true);
  });

  it('sends the address and says what the server answered, with no trial countdown', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockHostConfig);
    await openHostIpConfigModal();
    document.getElementById('net-host-ip-input').value = '192.168.1.51';
    document.getElementById('net-host-gateway-input').value = '192.168.1.1';
    const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'ok', message: 'Address saved' });
    await applyHostIpConfig();
    expect(postSpy).toHaveBeenCalledWith('/api/network/host/apply', {
      mode: 'static',
      interface: 'br0',
      ip_address: '192.168.1.51',
      netmask: '255.255.255.0',
      gateway: '192.168.1.1',
      dns1: '192.168.1.1',
      dns2: '1.1.1.1',
    });
    expect(document.getElementById('network-host-config-overlay').style.display).toBe('none');
    expect(toastSpy).toHaveBeenCalledWith('Address saved', 'success');
    expect(document.getElementById('network-canary-overlay')).toBeNull();
  });

  it('shows the refusal of a host Kiboto does not manage', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(mockHostConfig);
    await openHostIpConfigModal();
    document.getElementById('net-host-ip-input').value = '192.168.1.51';
    document.getElementById('net-host-gateway-input').value = '192.168.1.1';
    const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('This is changed in Unraid: Settings, Network Settings, not in Kiboto.'));
    await applyHostIpConfig();
    expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('Unraid'), 'error');
  });
});
