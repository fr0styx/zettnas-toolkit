import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  openHostIpConfigModal,
  closeHostIpConfigModal,
  applyHostIpConfig,
  openCanaryModal,
  closeCanaryModal,
  confirmCanaryConfig,
  revertCanaryConfig,
  initNetworkControls,
} from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('Host IP & DNS Administration with 60s Canary Watchdog (Tier 2)', () => {
  let container;

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement('div');
    container.innerHTML = `
      <div id="net-kpi-ip-card">
        <button id="btn-open-host-ip-modal"></button>
        <div id="net-kpi-ip">10.40.30.249</div>
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

      <!-- Canary Watchdog Modal -->
      <div id="network-canary-overlay" style="display: none;">
        <div id="net-canary-timer-circle">
          <span id="net-canary-timer-digits">60</span>
        </div>
        <span id="net-canary-target-url"></span>
        <a id="net-canary-open-link" href="#"></a>
        <div id="net-canary-reverting-msg" style="display: none;"></div>
        <button id="net-canary-confirm-btn"></button>
        <button id="net-canary-revert-btn"></button>
      </div>
    `;
    document.body.appendChild(container);
    initNetworkControls();
  });

  afterEach(() => {
    closeCanaryModal();
    container?.remove();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  const mockHostConfig = {
    status: 'ok',
    mode: 'static',
    interface: 'br0',
    available_interfaces: ['br0', 'eth0', 'eth1'],
    ip_address: '10.40.30.249',
    netmask: '255.255.255.0',
    cidr: 24,
    gateway: '10.40.30.1',
    dns1: '10.40.30.1',
    dns2: '1.1.1.1',
    dns_servers: ['10.40.30.1', '1.1.1.1'],
    canary: { is_active: false, expires_in: 0 },
  };

  it('opens Host IP modal and populates static IP, gateway, and DNS fields', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockHostConfig);

    await openHostIpConfigModal();

    const overlay = document.getElementById('network-host-config-overlay');
    expect(overlay.style.display).toBe('flex');
    expect(document.getElementById('net-host-ip-input').value).toBe('10.40.30.249');
    expect(document.getElementById('net-host-netmask-input').value).toBe('255.255.255.0');
    expect(document.getElementById('net-host-gateway-input').value).toBe('10.40.30.1');
    expect(document.getElementById('net-host-dns1-input').value).toBe('10.40.30.1');
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

  it('arms 60s Canary Watchdog when applying host IP changes', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(mockHostConfig);
    await openHostIpConfigModal();

    // Change IP
    document.getElementById('net-host-ip-input').value = '10.40.30.250';
    document.getElementById('net-host-gateway-input').value = '10.40.30.1';

    const mockCanaryResponse = {
      status: 'testing',
      canary_id: 'test_canary_abc',
      expires_in: 60,
      target_ip: '10.40.30.250',
      target_url: 'http://10.40.30.250:8082',
    };

    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce(mockCanaryResponse);

    await applyHostIpConfig();

    expect(postSpy).toHaveBeenCalledWith('/api/network/host/apply', {
      mode: 'static',
      interface: 'br0',
      ip_address: '10.40.30.250',
      netmask: '255.255.255.0',
      gateway: '10.40.30.1',
      dns1: '10.40.30.1',
      dns2: '1.1.1.1',
      timeout_sec: 60,
    });

    // Host config modal should close, Canary modal should open
    expect(document.getElementById('network-host-config-overlay').style.display).toBe('none');
    const canaryModal = document.getElementById('network-canary-overlay');
    expect(canaryModal.style.display).toBe('flex');
    expect(document.getElementById('net-canary-timer-digits').textContent).toBe('60');
    expect(document.getElementById('net-canary-target-url').textContent).toBe('http://10.40.30.250:8082');

    // Advance timer 10s
    vi.advanceTimersByTime(10000);
    expect(document.getElementById('net-canary-timer-digits').textContent).toBe('50');

    // Advance timer to dangerous threshold (<= 15s)
    vi.advanceTimersByTime(36000);
    expect(document.getElementById('net-canary-timer-digits').textContent).toBe('14');
    expect(document.getElementById('net-canary-timer-circle').classList.contains('danger')).toBe(true);
  });

  it('confirms Canary settings and closes modal on confirm', async () => {
    openCanaryModal({
      canary_id: 'canary_123',
      expires_in: 60,
      target_url: 'http://10.40.30.250:8082',
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'confirmed' });
    const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    vi.spyOn(api, 'get').mockResolvedValueOnce({ status: 'ok', summary: {}, physical_interfaces: [] });

    await confirmCanaryConfig();

    expect(postSpy).toHaveBeenCalledWith('/api/network/host/confirm', { canary_id: 'canary_123' });
    expect(toastSpy).toHaveBeenCalledWith(expect.any(String), 'success');
    expect(document.getElementById('network-canary-overlay').style.display).toBe('none');
  });

  it('reverts Canary settings and closes modal on revert', async () => {
    openCanaryModal({
      canary_id: 'canary_456',
      expires_in: 60,
      target_url: 'http://10.40.30.250:8082',
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'reverted' });
    const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});
    vi.spyOn(api, 'get').mockResolvedValueOnce({ status: 'ok', summary: {}, physical_interfaces: [] });

    await revertCanaryConfig();

    expect(postSpy).toHaveBeenCalledWith('/api/network/host/revert', { canary_id: 'canary_456' });
    expect(toastSpy).toHaveBeenCalledWith(expect.any(String), 'info');
    expect(document.getElementById('network-canary-overlay').style.display).toBe('none');
  });
});
