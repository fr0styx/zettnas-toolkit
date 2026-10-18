import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  renderUpsTelemetry,
  fetchAndRenderUpsEvents,
  fetchAndRenderUpsTelemetry,
  openUpsDrawer,
  closeUpsDrawer,
  loadUpsConfigToDrawer,
  initUpsDrawerControls,
  updateUpsConnCardState,
  saveUpsConfigFromDrawer,
  setUpsConfigLoaded,
} from '../components/management.js';
import { api } from '../api.js';

describe('UPS Power Flow Digital Twin & Drawer Controls', () => {
  beforeEach(() => {
    setUpsConfigLoaded(false);
    document.body.innerHTML = `
      <div id="mgmt-sec-ups">
        <span id="mgmt-ups-status">-</span>
        <span id="mgmt-ups-model">-</span>
        <span id="mgmt-ups-charge">-</span>
        <span id="mgmt-ups-runtime">-</span>
        <span id="mgmt-ups-load">-</span>
        <span id="mgmt-ups-linev">-</span>
        <span id="mgmt-ups-protocol">-</span>
        <span id="mgmt-ups-battv">-</span>
        <span id="mgmt-ups-policy">-</span>
        <span id="mgmt-hub-ups-pill">-</span>
        <span id="mgmt-sidebar-ups-badge" style="display:none;">-</span>

        <div id="ups-emergency-banner" style="display:none;">
          <span id="ups-emergency-countdown">--:--</span>
        </div>

        <div id="ups-permission-banner" style="display:none;">
          <span id="ups-permission-msg"></span>
        </div>

        <div id="ups-power-flow-container">
          <div id="ups-card-grid">
            <div id="ups-grid-dot"></div>
            <div id="ups-twin-linev">-- V</div>
            <div id="ups-twin-grid-status">--</div>
          </div>
          <div id="ups-card-battery">
            <svg>
              <circle id="ups-radial-fill" style="stroke-dashoffset: 0;"></circle>
            </svg>
            <div id="mgmt-ups-charge">--%</div>
            <div id="mgmt-ups-runtime">-- min</div>
            <div id="ups-twin-batt-volts">-- V</div>
          </div>
          <div id="ups-card-host">
            <div id="ups-twin-watts">-- W</div>
            <div id="mgmt-ups-load">-- %</div>
            <div id="ups-twin-policy-badge">--</div>
          </div>
        </div>

        <table>
          <tbody id="ups-events-tbody"></tbody>
        </table>

        <button id="btn-open-ups-config">Configure</button>
        <button id="btn-run-ups-selftest">Self-Test</button>
        <button id="btn-refresh-ups">Refresh</button>
        <button id="btn-ups-simulate">Simulate</button>
      </div>

      <!-- Drawer -->
      <div id="ups-drawer-overlay" class="drawer-backdrop" style="display:none;"></div>
      <aside id="ups-config-drawer" class="slide-drawer" style="display:none;">
        <button id="btn-close-ups-drawer">✕</button>
        <button id="btn-ups-discover">Scan Hardware</button>
        <div id="ups-discover-candidates"></div>

        <input type="radio" name="ups-mode" value="auto" checked>
        <input type="radio" name="ups-mode" value="apcupsd_client">
        <input type="radio" name="ups-mode" value="nut_client">
        <input type="radio" name="ups-mode" value="usb_hid">

        <div id="ups-toggle-params-container" style="display:none;">
          <button id="btn-toggle-ups-conn-params"><span id="ups-toggle-params-text"></span></button>
        </div>

        <div class="drawer-card" id="ups-drawer-conn-card">
          <span id="ups-conn-disabled-badge" style="display:none;"></span>
          <input type="text" id="ups-cfg-host" value="127.0.0.1">
          <input type="number" id="ups-cfg-port" value="3551">
          <input type="text" id="ups-cfg-name" value="ups">
          <input type="text" id="ups-cfg-user" value="">
          <input type="password" id="ups-cfg-pass" value="">
          <button id="btn-ups-test-conn">Test Connection</button>
        </div>

        <div id="ups-policy-card">
          <button id="btn-toggle-ups-policy"><span id="ups-toggle-policy-text">Collapse Policy</span></button>
          <div id="ups-policy-summary" style="display:none;"><span id="ups-policy-summary-text"></span></div>
          <div id="ups-policy-body" style="display:flex;">
            <input type="radio" name="ups-policy" value="runtime_left" checked>
            <input type="radio" name="ups-policy" value="battery_pct">
            <input type="radio" name="ups-policy" value="timer">

            <div id="ups-slider-runtime-container" style="display:flex;">
              <input type="range" id="ups-slider-runtime" min="2" max="25" value="5">
              <span id="ups-val-runtime">5 min</span>
            </div>

            <div id="ups-slider-battery-container" style="display:none;">
              <input type="range" id="ups-slider-battery" min="10" max="50" value="20">
              <span id="ups-val-battery">20 %</span>
            </div>

            <div id="ups-slider-timer-container" style="display:none;">
              <input type="range" id="ups-slider-timer" min="60" max="900" value="300">
              <span id="ups-val-timer">300 sec</span>
            </div>

            <input type="checkbox" id="ups-chk-docker" checked>
            <input type="checkbox" id="ups-chk-cutpower">
          </div>
        </div>

        <span id="ups-save-status" style="display:none;"></span>
      </aside>
    `;
    vi.restoreAllMocks();
  });

  it('renders online AC mains telemetry properly', () => {
    const ups = {
      available: true,
      status: 'ONLINE',
      on_battery: false,
      model: 'Smart-UPS 1500',
      battery_charge_pct: 100,
      time_left_min: 45,
      load_pct: 22,
      power_watts: 198,
      line_volts: 121.2,
      line_freq_hz: 60.0,
      battery_volts: 27.4,
      battery_temp_c: 29.0,
      protocol: 'apcupsd (NIS :3551)',
      active_policy: 'Runtime < 5m',
    };

    renderUpsTelemetry(ups);

    expect(document.getElementById('mgmt-ups-status').textContent).toBe('ONLINE');
    expect(document.getElementById('mgmt-ups-model').textContent).toBe('Smart-UPS 1500');
    expect(document.getElementById('mgmt-ups-charge').textContent).toBe('100%');
    expect(document.getElementById('mgmt-ups-runtime').textContent).toBe('45 min');
    expect(document.getElementById('mgmt-ups-linev').textContent).toBe('121.2 V');
    expect(document.getElementById('ups-twin-watts').textContent).toBe('198 W');
    expect(document.getElementById('ups-twin-batt-volts').textContent).toContain('27.4 V');

    const banner = document.getElementById('ups-emergency-banner');
    expect(banner.style.display).toBe('none');

    const flow = document.getElementById('ups-power-flow-container');
    expect(flow.classList.contains('on-battery')).toBe(false);
  });

  it('triggers emergency banner and on-battery states during outage', () => {
    const ups = {
      available: true,
      status: 'ONBATT',
      on_battery: true,
      model: 'CyberPower CP1500',
      battery_charge_pct: 75,
      time_left_min: 18,
      load_pct: 35,
      power_watts: 315,
      line_volts: 0.0,
      battery_volts: 24.1,
      protocol: 'NUT (TCP :3493)',
      active_policy: 'Battery < 20%',
    };

    renderUpsTelemetry(ups);

    expect(document.getElementById('mgmt-ups-status').textContent).toBe('ONBATT');
    const banner = document.getElementById('ups-emergency-banner');
    expect(banner.style.display).toBe('flex');
    expect(document.getElementById('ups-emergency-countdown').textContent).toBe('~18m remaining');

    const flow = document.getElementById('ups-power-flow-container');
    expect(flow.classList.contains('on-battery')).toBe(true);
    expect(flow.classList.contains('critical-battery')).toBe(false);

    const gridDot = document.getElementById('ups-grid-dot');
    expect(gridDot.classList.contains('danger')).toBe(true);
  });

  it('triggers critical-battery state when battery drops below 20%', () => {
    const ups = {
      available: true,
      status: 'ONBATT LOWBATT',
      on_battery: true,
      battery_charge_pct: 15,
      time_left_min: 3,
      load_pct: 40,
      power_watts: 360,
      line_volts: 0.0,
      battery_volts: 22.0,
    };

    renderUpsTelemetry(ups);

    const flow = document.getElementById('ups-power-flow-container');
    expect(flow.classList.contains('critical-battery')).toBe(true);
  });

  it('fetches and renders UPS outage events into ledger', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      events: [
        {
          id: 1,
          event_type: 'OUTAGE_START',
          ts: 1775685600,
          duration_sec: 120,
          start_battery_pct: 100,
          end_battery_pct: 85,
          action_taken: 'Running on battery',
        },
        {
          id: 2,
          event_type: 'SELF_TEST_PASS',
          ts: 1775685000,
          duration_sec: 10,
          start_battery_pct: 100,
          end_battery_pct: 99,
          action_taken: 'OK',
        },
      ],
    });

    await fetchAndRenderUpsEvents();

    const tbody = document.getElementById('ups-events-tbody');
    expect(tbody.querySelectorAll('tr').length).toBe(2);
    expect(tbody.innerHTML).toContain('OUTAGE_START');
    expect(tbody.innerHTML).toContain('SELF_TEST_PASS');
    expect(tbody.innerHTML).toContain('120s');
    expect(tbody.innerHTML).toContain('100% ➔ 85%');
  });

  it('handles empty events gracefully', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ events: [] });
    await fetchAndRenderUpsEvents();

    const tbody = document.getElementById('ups-events-tbody');
    expect(tbody.innerHTML).toContain('No power events or brownouts recorded');
  });

  it('opens and closes the configuration drawer', () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    openUpsDrawer();
    const drawer = document.getElementById('ups-config-drawer');
    const overlay = document.getElementById('ups-drawer-overlay');
    expect(drawer.classList.contains('open')).toBe(true);
    expect(overlay.classList.contains('open')).toBe(true);

    closeUpsDrawer();
    expect(drawer.classList.contains('open')).toBe(false);
    expect(overlay.classList.contains('open')).toBe(false);
  });

  it('loads configuration to drawer inputs and sliders', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      enabled: true,
      mode: 'nut_client',
      host: '192.168.1.50',
      port: 3493,
      ups_name: 'rack_ups',
      username: 'monuser',
      password: 'masked_secret',
      shutdown_policy: 'battery_pct',
      runtime_threshold_min: 8,
      battery_threshold_pct: 25,
      shutdown_timer_sec: 420,
      container_shutdown_timeout_sec: 30,
      poweroff_ups: true,
    });

    await loadUpsConfigToDrawer();

    const nutRadio = document.querySelector('input[name="ups-mode"][value="nut_client"]');
    expect(nutRadio.checked).toBe(true);
    expect(document.getElementById('ups-cfg-host').value).toBe('192.168.1.50');
    expect(document.getElementById('ups-cfg-port').value).toBe('3493');
    expect(document.getElementById('ups-cfg-name').value).toBe('rack_ups');
    expect(document.getElementById('ups-slider-battery').value).toBe('25');
    expect(document.getElementById('ups-val-battery').textContent).toBe('25 %');
    expect(document.getElementById('ups-chk-cutpower').checked).toBe(true);
    expect(document.getElementById('ups-drawer-conn-card').classList.contains('disabled')).toBe(false);
  });

  it('automatically hides and grays out connection parameters card when Direct USB mode is selected', () => {
    updateUpsConnCardState('usb_hid');
    const connCard = document.getElementById('ups-drawer-conn-card');
    const badge = document.getElementById('ups-conn-disabled-badge');
    expect(connCard.classList.contains('disabled')).toBe(true);
    expect(connCard.getAttribute('aria-disabled')).toBe('true');
    expect(connCard.style.display).toBe('none');
    expect(badge.style.display).toBe('inline-flex');

    const inputs = connCard.querySelectorAll('input, button');
    inputs.forEach(el => {
      expect(el.disabled).toBe(true);
    });

    // Re-enabling and showing when switching to APCUPSD
    updateUpsConnCardState('apcupsd_client');
    expect(connCard.classList.contains('disabled')).toBe(false);
    expect(connCard.hasAttribute('aria-disabled')).toBe(false);
    expect(connCard.style.display).not.toBe('none');
    expect(badge.style.display).toBe('none');
    inputs.forEach(el => {
      expect(el.disabled).toBe(false);
    });
  });

  it('allows manual expansion/collapse of connection parameters card when in Direct USB mode', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    await initUpsDrawerControls();

    const usbRadio = document.querySelector('input[name="ups-mode"][value="usb_hid"]');
    usbRadio.checked = true;
    updateUpsConnCardState('usb_hid');
    const connCard = document.getElementById('ups-drawer-conn-card');
    const toggleBtn = document.getElementById('btn-toggle-ups-conn-params');
    expect(connCard.style.display).toBe('none');

    // Click toggle to reveal
    toggleBtn.dispatchEvent(new Event('click'));
    expect(connCard.style.display).not.toBe('none');

    // Click toggle again to re-hide
    toggleBtn.dispatchEvent(new Event('click'));
    expect(connCard.style.display).toBe('none');
  });

  it('automatically hides connection parameters card when loading usb_hid config', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      enabled: true,
      mode: 'usb_hid',
      shutdown_policy: 'runtime_left',
      runtime_threshold_min: 6,
    });

    await loadUpsConfigToDrawer();

    const usbRadio = document.querySelector('input[name="ups-mode"][value="usb_hid"]');
    expect(usbRadio.checked).toBe(true);
    const connCard = document.getElementById('ups-drawer-conn-card');
    expect(connCard.classList.contains('disabled')).toBe(true);
    expect(connCard.style.display).toBe('none');
    expect(document.getElementById('ups-cfg-host').disabled).toBe(true);
  });

  it('suppresses auto-save if configuration has not loaded yet (prevents race condition overwrites)', async () => {
    setUpsConfigLoaded(false);
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ success: true });
    await saveUpsConfigFromDrawer();
    expect(postSpy).not.toHaveBeenCalled();
  });

  it('automatically saves configuration when sliders, policy, or toggles change without needing a save button', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ success: true });
    await initUpsDrawerControls();

    // 1. Moving slider
    const runtimeSlider = document.getElementById('ups-slider-runtime');
    runtimeSlider.value = '12';
    runtimeSlider.dispatchEvent(new Event('change'));

    expect(postSpy).toHaveBeenCalledWith('/api/ups/config', expect.objectContaining({
      runtime_threshold_min: 12,
    }));

    // 2. Changing policy radio
    const battPolicyRadio = document.querySelector('input[name="ups-policy"][value="battery_pct"]');
    battPolicyRadio.checked = true;
    battPolicyRadio.dispatchEvent(new Event('change'));

    expect(postSpy).toHaveBeenCalledWith('/api/ups/config', expect.objectContaining({
      shutdown_policy: 'battery_pct',
    }));

    // 3. Changing cut-power toggle
    const chkCutpower = document.getElementById('ups-chk-cutpower');
    chkCutpower.checked = true;
    chkCutpower.dispatchEvent(new Event('change'));

    expect(postSpy).toHaveBeenCalledWith('/api/ups/config', expect.objectContaining({
      poweroff_ups: true,
    }));

    // 4. Changing mode to usb_hid
    const usbRadio = document.querySelector('input[name="ups-mode"][value="usb_hid"]');
    usbRadio.checked = true;
    usbRadio.dispatchEvent(new Event('change'));

    expect(postSpy).toHaveBeenCalledWith('/api/ups/config', expect.objectContaining({
      mode: 'usb_hid',
    }));
    const connCard = document.getElementById('ups-drawer-conn-card');
    expect(connCard.classList.contains('disabled')).toBe(true);
  });

  it('renders permission_error banner and status when Docker lacks hidraw permissions', () => {
    const ups = {
      available: true,
      permission_error: true,
      permission_detail: 'Docker lacks permission to open /dev/hidraw0. Add device_cgroup_rules or privileged: true.',
      status: 'Permission Required',
      model: 'WalleCube (Smart UPS W180)',
      on_battery: false,
    };

    renderUpsTelemetry(ups);

    expect(document.getElementById('mgmt-ups-status').textContent).toBe('Permission Required');
    expect(document.getElementById('mgmt-ups-status').style.color).toContain('eb5757');
    expect(document.getElementById('mgmt-hub-ups-pill').textContent).toBe('Perm Req');

    const permBanner = document.getElementById('ups-permission-banner');
    expect(permBanner.style.display).toBe('flex');
    expect(document.getElementById('ups-permission-msg').textContent).toContain('device_cgroup_rules');
  });

  it('handles direct USB discovery candidate selection without setting localhost or port', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    const postSpy = vi.spyOn(api, 'post').mockImplementation((url) => {
      if (url === '/api/ups/discover') {
        return Promise.resolve({
          candidates: [
            {
              type: 'usb_hid',
              mode: 'usb_hid',
              title: 'WalleCube / OpenUPS (Smart UPS W180)',
              label: 'WalleCube / OpenUPS (Smart UPS W180)',
              vendor_id: '04d8',
              product_id: 'd005',
              is_usb: true,
              host: '',
              port: null,
            },
          ],
        });
      }
      return Promise.resolve({ success: true });
    });

    await initUpsDrawerControls();

    const btnDiscover = document.getElementById('btn-ups-discover');
    btnDiscover.click();

    // Allow promise microtask to resolve
    await new Promise((r) => setTimeout(r, 10));

    const item = document.querySelector('.ups-discover-item');
    expect(item).not.toBeNull();
    expect(item.textContent).toContain('WalleCube');
    expect(item.textContent).toContain('Direct USB HID');

    // Clicking the item to apply
    item.click();

    const usbRadio = document.querySelector('input[name="ups-mode"][value="usb_hid"]');
    expect(usbRadio.checked).toBe(true);
    expect(document.getElementById('ups-cfg-host').value).toBe('');
    expect(document.getElementById('ups-cfg-port').value).toBe('');

    expect(postSpy).toHaveBeenCalledWith('/api/ups/config', expect.objectContaining({
      mode: 'usb_hid',
    }));
  });

  it('hides connection parameters card in auto mode when UPS telemetry indicates is_usb: true', () => {
    updateUpsConnCardState('auto', { is_usb: true, protocol: 'apcupsd_socket' });
    const connCard = document.getElementById('ups-drawer-conn-card');
    const badge = document.getElementById('ups-conn-disabled-badge');
    expect(connCard.style.display).toBe('none');
    expect(connCard.classList.contains('disabled')).toBe(true);
    expect(badge.style.display).toBe('inline-flex');
  });

  it('switches visible slider container based on active shutdown policy (accordion)', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    vi.spyOn(api, 'post').mockResolvedValue({ success: true });
    await initUpsDrawerControls();

    const rtBox = document.getElementById('ups-slider-runtime-container');
    const battBox = document.getElementById('ups-slider-battery-container');
    const timerBox = document.getElementById('ups-slider-timer-container');

    const battRadio = document.querySelector('input[name="ups-policy"][value="battery_pct"]');
    battRadio.checked = true;
    battRadio.dispatchEvent(new Event('change'));

    expect(rtBox.style.display).toBe('none');
    expect(battBox.style.display).toBe('flex');
    expect(timerBox.style.display).toBe('none');

    const timerRadio = document.querySelector('input[name="ups-policy"][value="timer"]');
    timerRadio.checked = true;
    timerRadio.dispatchEvent(new Event('change'));

    expect(rtBox.style.display).toBe('none');
    expect(battBox.style.display).toBe('none');
    expect(timerBox.style.display).toBe('flex');
  });

  it('collapses and expands the Safe Shutdown Policy card via the toggle button', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({});
    await initUpsDrawerControls();

    const btnTogglePolicy = document.getElementById('btn-toggle-ups-policy');
    const policyBody = document.getElementById('ups-policy-body');
    const policySummary = document.getElementById('ups-policy-summary');

    expect(policyBody.style.display).not.toBe('none');
    expect(policySummary.style.display).toBe('none');

    // Click to collapse
    btnTogglePolicy.click();
    expect(policyBody.style.display).toBe('none');
    expect(policySummary.style.display).toBe('flex');

    // Click to expand again
    btnTogglePolicy.click();
    expect(policyBody.style.display).toBe('flex');
    expect(policySummary.style.display).toBe('none');
  });
});
