import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { openStackPickerModal, _resetStackModalForTesting } from '../components/stack-modal.js';
import {
  startDockerAutoRefresh,
  stopDockerAutoRefresh,
  fetchAndRenderDockerContainers,
  _resetDockerStateForTesting
} from '../components/management.js';
import { api } from '../api.js';

describe('Stack Picker Modal, Auto-Refresh & Context Menu Polishing', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    _resetStackModalForTesting();
    _resetDockerStateForTesting();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    stopDockerAutoRefresh();
    _resetStackModalForTesting();
    _resetDockerStateForTesting();
    vi.restoreAllMocks();
  });

  it('renders native glassmorphic stack picker modal with stack cards and status pills', () => {
    const mockStacks = [
      {
        name: 'arr',
        origin: 'compose',
        working_dir: '/mnt/user/appdata/arr',
        total_count: 10,
        running_count: 10,
        services: ['sonarr', 'radarr', 'prowlarr', 'bazarr']
      },
      {
        name: 'immich-prod',
        origin: 'compose',
        working_dir: '/mnt/user/appdata/immich',
        total_count: 4,
        running_count: 4,
        services: ['immich-server', 'immich-machine-learning', 'redis', 'postgres']
      },
      {
        name: 'test-stopped',
        origin: 'compose',
        working_dir: '/mnt/user/appdata/test',
        total_count: 2,
        running_count: 0,
        services: ['app', 'db']
      }
    ];

    openStackPickerModal(mockStacks);

    const overlay = document.getElementById('stack-picker-overlay');
    expect(overlay).not.toBeNull();
    expect(overlay.style.display).toBe('flex');
    expect(overlay.classList.contains('open')).toBe(true);

    const badge = overlay.querySelector('#stack-picker-badge');
    expect(badge.textContent).toBe('3 Stacks');

    const cards = overlay.querySelectorAll('.stack-picker-card');
    expect(cards.length).toBe(3);
    expect(cards[0].textContent).toContain('arr');
    expect(cards[0].textContent).toContain('10/10 Running');
    expect(cards[1].textContent).toContain('immich-prod');
    expect(cards[1].textContent).toContain('4/4 Running');
    expect(cards[2].textContent).toContain('test-stopped');
    expect(cards[2].textContent).toContain('Stopped (2)');
  });

  it('filters stacks in real-time when typing in search input', () => {
    const mockStacks = [
      { name: 'arr', origin: 'compose', working_dir: '/mnt/user/appdata/arr', total_count: 1, running_count: 1, services: ['sonarr'] },
      { name: 'immich-prod', origin: 'compose', working_dir: '/mnt/user/appdata/immich', total_count: 1, running_count: 1, services: ['redis'] }
    ];

    openStackPickerModal(mockStacks);
    const searchInput = document.getElementById('stack-picker-search');
    expect(searchInput).not.toBeNull();

    // Type "immich"
    searchInput.value = 'immich';
    searchInput.dispatchEvent(new Event('input'));

    let cards = document.querySelectorAll('.stack-picker-card');
    expect(cards.length).toBe(1);
    expect(cards[0].textContent).toContain('immich-prod');

    // Type query that matches nothing
    searchInput.value = 'nonexistent';
    searchInput.dispatchEvent(new Event('input'));

    cards = document.querySelectorAll('.stack-picker-card');
    expect(cards.length).toBe(0);
    expect(document.getElementById('stack-picker-list').textContent).toContain('No Compose stacks match "nonexistent"');
  });

  it('manages auto-refresh interval lifecycle cleanly', async () => {
    vi.useFakeTimers();

    // Setup dummy DOM for management window and docker section
    document.body.innerHTML = `
      <div id="management-window" style="display: block;">
        <div id="mgmt-sec-docker" style="display: block;">
          <table><tbody id="docker-containers-tbody"></tbody></table>
        </div>
      </div>
    `;

    const getSpy = vi.spyOn(api, 'get').mockResolvedValue([]);

    startDockerAutoRefresh();

    // Fast-forward 5000ms
    await vi.advanceTimersByTimeAsync(5000);
    const containerCalls1 = getSpy.mock.calls.filter((c) => c[0] === '/api/docker/containers');
    expect(containerCalls1.length).toBe(1);

    await vi.advanceTimersByTimeAsync(5000);
    const containerCalls2 = getSpy.mock.calls.filter((c) => c[0] === '/api/docker/containers');
    expect(containerCalls2.length).toBe(2);

    stopDockerAutoRefresh();
    await vi.advanceTimersByTimeAsync(10000);
    const containerCalls3 = getSpy.mock.calls.filter((c) => c[0] === '/api/docker/containers');
    expect(containerCalls3.length).toBe(2); // no further calls

    vi.useRealTimers();
  });
});
