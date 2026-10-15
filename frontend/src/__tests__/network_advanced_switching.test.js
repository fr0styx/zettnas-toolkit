import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  openBondConfigModal,
  closeBondConfigModal,
  saveBondConfig,
  openBridgeConfigModal,
  closeBridgeConfigModal,
  saveBridgeConfig,
  openCreateVlanModal,
  closeCreateVlanModal,
  submitCreateVlan,
  deleteVlanSubinterface,
  initNetworkControls,
} from '../components/management.js';
import { api } from '../api.js';
import * as toast from '../toast.js';

describe('Tier 3: Advanced Virtual Switching, Bonding & 802.1Q VLAN Tagging', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.innerHTML = `
      <!-- Trigger button for VLAN creation -->
      <button id="btn-open-create-vlan-modal"></button>

      <!-- Bonding Configuration Modal -->
      <div id="network-bond-config-overlay" style="display: none;">
        <span id="net-bond-target-badge">bond0</span>
        <button id="net-bond-cfg-close-btn"></button>
        <button id="net-bond-cfg-cancel-btn"></button>
        <button id="net-bond-cfg-save-btn"></button>

        <select id="net-bond-mode-select">
          <option value="1">Mode 1: Active-Backup</option>
          <option value="4">Mode 4: 802.3ad LACP</option>
          <option value="6">Mode 6: Balance-ALB</option>
          <option value="0">Mode 0: Balance-RR</option>
          <option value="2">Mode 2: Balance-XOR</option>
        </select>
        <div id="net-bond-mode-desc"></div>
        <input id="net-bond-miimon-input" type="number" value="100" />
        <div id="net-bond-slaves-container" class="network-member-checkbox-list"></div>
      </div>

      <!-- Virtual Bridge Configuration Modal -->
      <div id="network-bridge-config-overlay" style="display: none;">
        <span id="net-bridge-target-badge">br0</span>
        <button id="net-bridge-cfg-close-btn"></button>
        <button id="net-bridge-cfg-cancel-btn"></button>
        <button id="net-bridge-cfg-save-btn"></button>

        <button type="button" class="net-stp-toggle-btn active" id="net-stp-btn-enable">Enabled</button>
        <button type="button" class="net-stp-toggle-btn" id="net-stp-btn-disable">Disabled</button>
        <input id="net-bridge-fd-input" type="number" value="0" />
        <div id="net-bridge-members-container" class="network-member-checkbox-list"></div>
      </div>

      <!-- 802.1Q VLAN Creation Modal -->
      <div id="network-vlan-create-overlay" style="display: none;">
        <button id="net-vlan-create-close-btn"></button>
        <button id="net-vlan-create-cancel-btn"></button>
        <button id="net-vlan-create-submit-btn"></button>

        <select id="net-vlan-parent-select"></select>
        <input id="net-vlan-id-input" type="number" />
        <input id="net-vlan-alias-input" type="text" />
      </div>

      <!-- Topology Containers -->
      <div id="network-bridges-container"></div>
      <table>
        <tbody id="network-vlan-tbody"></tbody>
      </table>
    `;
    document.body.appendChild(container);
    initNetworkControls();
  });

  afterEach(() => {
    closeBondConfigModal();
    closeBridgeConfigModal();
    closeCreateVlanModal();
    container?.remove();
    vi.restoreAllMocks();
  });

  const mockBondData = {
    bond: 'bond0',
    mode: '1',
    mode_name: 'active-backup',
    mode_title: 'Active-Backup (Failover)',
    miimon: 100,
    slaves: ['eth0'],
    active_slave: 'eth0',
    available_modes: [
      { code: '1', name: 'active-backup', title: 'Active-Backup', description: 'Active-backup policy' },
      { code: '4', name: '802.3ad', title: 'Dynamic Link Aggregation (802.3ad LACP)', description: 'LACP dynamic aggregation' },
    ],
    candidate_slaves: [
      { name: 'eth0', is_slave: true, is_up: true, speed_human: '1 Gbps' },
      { name: 'eth1', is_slave: false, is_up: true, speed_human: '1 Gbps' },
    ],
  };

  const mockBridgeData = {
    bridge: 'br0',
    stp: false,
    forward_delay: 0,
    members: ['bond0'],
    candidate_members: [
      { name: 'bond0', type: 'bond', is_member: true, is_up: true, speed_human: '2 Gbps' },
      { name: 'eth2', type: 'interface', is_member: false, is_up: false, speed_human: 'Disconnected' },
    ],
  };

  const mockTopology = {
    physical_interfaces: [{ name: 'eth0' }, { name: 'eth1' }],
    bonds: [{ name: 'bond0' }],
    bridges: [{ name: 'br0' }],
    vlans: [
      { name: 'eth0.10', parent: 'eth0', vlan_id: 10, is_up: true, ip_address: '192.168.10.1', alias: 'DMZ' },
    ],
  };

  beforeEach(() => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('/api/system/network-topology')) return mockTopology;
      if (url.includes('/api/network/bond/')) return mockBondData;
      if (url.includes('/api/network/bridge/')) return mockBridgeData;
      return {};
    });
  });

  describe('Bonding Configuration Modal', () => {
    it('opens bond modal, loads config, and populates candidates', async () => {
      vi.spyOn(api, 'get').mockResolvedValueOnce(mockBondData);

      await openBondConfigModal('bond0');

      const overlay = document.getElementById('network-bond-config-overlay');
      expect(overlay.style.display).toBe('flex');
      expect(document.getElementById('net-bond-target-badge').textContent).toBe('bond0');
      expect(document.getElementById('net-bond-mode-select').value).toBe('1');
      expect(document.getElementById('net-bond-miimon-input').value).toBe('100');

      const checkboxes = document.querySelectorAll('.net-bond-slave-checkbox');
      expect(checkboxes.length).toBe(2);
      expect(checkboxes[0].value).toBe('eth0');
      expect(checkboxes[0].checked).toBe(true);
      expect(checkboxes[1].value).toBe('eth1');
      expect(checkboxes[1].checked).toBe(false);
    });

    it('saves updated bond mode, miimon, and selected slaves', async () => {
      vi.spyOn(api, 'get').mockResolvedValueOnce(mockBondData);
      const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'ok' });
      const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});

      await openBondConfigModal('bond0');

      // Change mode to 4 (LACP) and check eth1 as well
      document.getElementById('net-bond-mode-select').value = '4';
      document.getElementById('net-bond-miimon-input').value = '200';
      const checkboxes = document.querySelectorAll('.net-bond-slave-checkbox');
      checkboxes[1].checked = true; // eth1 checked

      await saveBondConfig();

      expect(postSpy).toHaveBeenCalledWith('/api/network/bond/bond0', {
        mode: '4',
        slaves: ['eth0', 'eth1'],
        miimon: 200,
      });
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('successfully'), 'success');
      expect(document.getElementById('network-bond-config-overlay').style.display).toBe('none');
    });

    it('prevents saving bond with zero selected slaves', async () => {
      vi.spyOn(api, 'get').mockResolvedValueOnce(mockBondData);
      const postSpy = vi.spyOn(api, 'post');
      const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});

      await openBondConfigModal('bond0');

      // Uncheck all
      document.querySelectorAll('.net-bond-slave-checkbox').forEach((cb) => {
        cb.checked = false;
      });

      await saveBondConfig();

      expect(postSpy).not.toHaveBeenCalled();
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('at least one physical interface'), 'error');
    });
  });

  describe('Virtual Bridge Configuration Modal', () => {
    it('opens bridge modal, renders STP and candidate member ports', async () => {
      vi.spyOn(api, 'get').mockResolvedValueOnce(mockBridgeData);

      await openBridgeConfigModal('br0');

      const overlay = document.getElementById('network-bridge-config-overlay');
      expect(overlay.style.display).toBe('flex');
      expect(document.getElementById('net-bridge-target-badge').textContent).toBe('br0');

      const btnEnable = document.getElementById('net-stp-btn-enable');
      const btnDisable = document.getElementById('net-stp-btn-disable');
      expect(btnEnable.classList.contains('active')).toBe(false);
      expect(btnDisable.classList.contains('active')).toBe(true);

      const checkboxes = document.querySelectorAll('.net-bridge-member-checkbox');
      expect(checkboxes.length).toBe(2);
      expect(checkboxes[0].value).toBe('bond0');
      expect(checkboxes[0].checked).toBe(true);
    });

    it('toggles STP active classes and saves bridge configuration', async () => {
      vi.spyOn(api, 'get').mockResolvedValueOnce(mockBridgeData);
      const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'ok' });
      const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});

      await openBridgeConfigModal('br0');

      const btnEnable = document.getElementById('net-stp-btn-enable');
      btnEnable.click(); // Enables STP
      document.getElementById('net-bridge-fd-input').value = '15';

      await saveBridgeConfig();

      expect(postSpy).toHaveBeenCalledWith('/api/network/bridge/br0', {
        stp: true,
        forward_delay: 15,
        members: ['bond0'],
      });
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('successfully'), 'success');
      expect(document.getElementById('network-bridge-config-overlay').style.display).toBe('none');
    });
  });

  describe('802.1Q VLAN Sub-Interface Creation & Deletion', () => {
    it('opens create VLAN modal and populates parent trunk options', async () => {
      vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);

      await openCreateVlanModal();

      const overlay = document.getElementById('network-vlan-create-overlay');
      expect(overlay.style.display).toBe('flex');

      const parentSelect = document.getElementById('net-vlan-parent-select');
      expect(parentSelect.options.length).toBe(4); // 2 physical + 1 bond + 1 bridge
      expect(parentSelect.options[0].value).toBe('eth0');
      expect(parentSelect.options[2].value).toBe('bond0');
    });

    it('validates VLAN tag ID boundary (1 - 4094)', async () => {
      vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);
      const postSpy = vi.spyOn(api, 'post');
      const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});

      await openCreateVlanModal();

      document.getElementById('net-vlan-id-input').value = '5000'; // Out of range
      await submitCreateVlan();

      expect(postSpy).not.toHaveBeenCalled();
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('between 1 and 4094'), 'error');
    });

    it('submits valid VLAN sub-interface creation request', async () => {
      vi.spyOn(api, 'get').mockResolvedValueOnce(mockTopology);
      const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ status: 'ok' });
      const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});

      await openCreateVlanModal();

      document.getElementById('net-vlan-parent-select').value = 'eth0';
      document.getElementById('net-vlan-id-input').value = '20';
      document.getElementById('net-vlan-alias-input').value = 'IoT Network';

      await submitCreateVlan();

      expect(postSpy).toHaveBeenCalledWith('/api/network/vlan/create', {
        parent: 'eth0',
        vlan_id: 20,
        alias: 'IoT Network',
      });
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('successfully'), 'success');
      expect(document.getElementById('network-vlan-create-overlay').style.display).toBe('none');
    });

    it('deletes VLAN sub-interface after confirmation', async () => {
      const delSpy = vi.spyOn(api, 'delete').mockResolvedValueOnce({ status: 'ok' });
      const toastSpy = vi.spyOn(toast, 'showToast').mockImplementation(() => {});

      await deleteVlanSubinterface('eth0.20');
      const okBtn = document.getElementById('confirm-toast-ok');
      if (okBtn) okBtn.click();
      await Promise.resolve();

      expect(delSpy).toHaveBeenCalledWith('/api/network/vlan/eth0.20');
      expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('successfully'), 'success');
    });

    it('aborts VLAN deletion when confirmation is rejected', async () => {
      const delSpy = vi.spyOn(api, 'delete');

      await deleteVlanSubinterface('eth0.20');
      const cancelBtn = document.getElementById('confirm-toast-cancel');
      if (cancelBtn) cancelBtn.click();
      await Promise.resolve();

      expect(delSpy).not.toHaveBeenCalled();
    });
  });

  describe('UI Event Listeners & Modals Controls', () => {
    it('wires close and cancel buttons for all Tier 3 modals', () => {
      const bondOverlay = document.getElementById('network-bond-config-overlay');
      const bridgeOverlay = document.getElementById('network-bridge-config-overlay');
      const vlanOverlay = document.getElementById('network-vlan-create-overlay');

      bondOverlay.classList.add('open');
      bondOverlay.style.display = 'flex';
      document.getElementById('net-bond-cfg-close-btn').click();
      expect(bondOverlay.style.display).toBe('none');
      expect(bondOverlay.classList.contains('open')).toBe(false);

      bridgeOverlay.classList.add('open');
      bridgeOverlay.style.display = 'flex';
      document.getElementById('net-bridge-cfg-cancel-btn').click();
      expect(bridgeOverlay.style.display).toBe('none');
      expect(bridgeOverlay.classList.contains('open')).toBe(false);

      vlanOverlay.classList.add('open');
      vlanOverlay.style.display = 'flex';
      document.getElementById('net-vlan-create-close-btn').click();
      expect(vlanOverlay.style.display).toBe('none');
      expect(vlanOverlay.classList.contains('open')).toBe(false);
    });
  });
});
