import { describe, it, expect, beforeEach, vi } from 'vitest';
import { api } from '../api.js';
import { openContainerDeleteModal } from '../components/container-modal.js';
import { openDockerPruneModal, fetchAndRenderAppCatalog } from '../components/management.js';

describe('Container Deletion and Docker Prune Subsystem', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="os-dock-container"></div>
      <div id="i-chip"></div>
      <div id="mgmt-pane-docker">
        <button id="btn-view-docker-containers" class="active"></button>
        <button id="btn-view-docker-catalog"></button>
        <button id="btn-docker-prune"></button>
        <div id="docker-view-containers-wrap">
          <table id="docker-containers-table">
            <tbody id="docker-containers-tbody"></tbody>
          </table>
        </div>
        <div id="docker-view-catalog-wrap" style="display:none;">
          <div id="docker-catalog-grid"></div>
        </div>
      </div>
    `;
    vi.restoreAllMocks();
  });

  it('updates Uptime Kuma to use next image tag in app catalog', async () => {
    const mockCatalog = [
      {
        id: 'uptime-kuma',
        name: 'Uptime Kuma',
        category: 'utilities',
        description: 'Self-hosted monitoring tool.',
        image: 'louislam/uptime-kuma:next',
        default_port: 3001,
      },
    ];

    vi.spyOn(api, 'get').mockResolvedValue(mockCatalog);
    await fetchAndRenderAppCatalog();

    const grid = document.getElementById('docker-catalog-grid');
    expect(grid.textContent).toContain('Uptime Kuma');
    expect(grid.textContent).toContain('louislam/uptime-kuma:next');
  });

  it('opens container delete modal and executes container destruction with volume and image options', async () => {
    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValue({
      success: true,
      container_id: 'c123',
      name: 'uptime-kuma',
      removed: true,
      volumes_removed: true,
      image_removed: true,
    });

    const onDeletedMock = vi.fn();
    openContainerDeleteModal('c123456789012', 'uptime-kuma', 'louislam/uptime-kuma:next', onDeletedMock);

    const modal = document.getElementById('container-delete-modal-overlay');
    expect(modal).toBeTruthy();
    expect(modal.classList.contains('open')).toBe(true);
    expect(modal.style.display).toBe('flex');

    const cnameEl = document.getElementById('cdm-cname');
    expect(cnameEl.textContent).toBe('uptime-kuma');

    const forceCb = document.getElementById('cdm-force');
    const volumesCb = document.getElementById('cdm-volumes');
    const imageCb = document.getElementById('cdm-image');
    expect(forceCb.checked).toBe(true);
    expect(volumesCb.checked).toBe(true);
    expect(imageCb.checked).toBe(false);

    // Toggle remove image to true
    imageCb.checked = true;

    const confirmBtn = document.getElementById('cdm-confirm-btn');
    await confirmBtn.onclick();

    expect(deleteSpy).toHaveBeenCalledWith(
      '/api/docker/containers/c123456789012?force=true&remove_volumes=true&remove_image=true'
    );
    expect(onDeletedMock).toHaveBeenCalled();
    expect(modal.classList.contains('open')).toBe(false);
    expect(modal.style.display).toBe('none');
  });

  it('opens docker prune modal, displays df stats, and triggers prune API', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      images: { total_count: 5, unused_count: 2 },
      containers: { total_count: 8, stopped_count: 3 },
      volumes: { total_count: 10, unused_count: 4 },
      total_reclaimable_human: '1.2 GB',
    });

    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      space_reclaimed_bytes: 1288490188,
      space_reclaimed_human: '1.2 GB',
      containers_deleted_count: 3,
      images_deleted_count: 2,
      volumes_deleted_count: 4,
    });

    await openDockerPruneModal();

    const modal = document.getElementById('docker-prune-modal-overlay');
    expect(modal).toBeTruthy();
    expect(modal.classList.contains('open')).toBe(true);
    expect(modal.style.display).toBe('flex');

    const recEl = document.getElementById('dpm-df-reclaimable');
    expect(recEl.textContent).toBe('1.2 GB');

    const confirmBtn = document.getElementById('dpm-confirm-btn');
    await confirmBtn.onclick();

    expect(postSpy).toHaveBeenCalledWith('/api/docker/system/prune', {
      prune_containers: true,
      prune_images: true,
      all_images: false,
      prune_volumes: false,
      prune_networks: true,
      prune_build_cache: true,
    });

    expect(modal.classList.contains('open')).toBe(false);
    expect(modal.style.display).toBe('none');
  });
});
