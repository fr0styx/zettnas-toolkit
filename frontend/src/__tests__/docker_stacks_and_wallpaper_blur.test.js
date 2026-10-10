import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '../api.js';
import { TRANSLATIONS } from '../i18n.js';
import {
  initStackModal,
  openStackModal,
  closeStackModal,
  switchStackTab,
  _resetStackModalForTesting,
} from '../components/stack-modal.js';
import { setWallpaper } from '../components/wallpapers.js';
import fs from 'fs';
import path from 'path';

describe('Docker Stacks & Wallpaper Blur & Dock Labels', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="desktop-wallpaper" class="desktop-wallpaper" style="background-image: none;"></div>
      <div id="desktop-wallpaper-dimmer" class="desktop-wallpaper-dimmer"></div>
    `;
    _resetStackModalForTesting();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    _resetStackModalForTesting();
    vi.restoreAllMocks();
  });

  describe('Dock and Desktop Labels - macOS Removal', () => {
    it('verifies that no translation contains "macOS" in dock labels', () => {
      for (const lang of Object.keys(TRANSLATIONS)) {
        const t = TRANSLATIONS[lang];
        if (t['mgmt.dock_sec_desc']) {
          expect(t['mgmt.dock_sec_desc'].toLowerCase()).not.toContain('macos');
        }
        if (t['mgmt.dock_magnification_title']) {
          expect(t['mgmt.dock_magnification_title'].toLowerCase()).not.toContain('macos');
        }
      }
    });

    it('verifies index.html does not contain "macOS Parabolic Magnification" or "macOS Standard"', () => {
      const htmlPath = path.resolve(__dirname, '../../../frontend/index.html');
      const htmlContent = fs.readFileSync(htmlPath, 'utf8');
      expect(htmlContent).not.toContain('macOS Parabolic Magnification');
      expect(htmlContent).not.toContain('macOS Standard');
      expect(htmlContent).toContain('Parabolic Magnification');
      expect(htmlContent).toContain('Standard');
    });
  });

  describe('Wallpaper Dedicated Layer & Blur Architecture', () => {
    it('verifies #desktop-wallpaper layer receives background-image update', () => {
      const layer = document.getElementById('desktop-wallpaper');
      expect(layer).not.toBeNull();

      setWallpaper('/api/wallpapers/lake.jpg');
      expect(layer.style.backgroundImage).toContain('/api/wallpapers/lake.jpg');
    });

    it('verifies index.html declares #desktop-wallpaper before dimmer layer', () => {
      const htmlPath = path.resolve(__dirname, '../../../frontend/index.html');
      const htmlContent = fs.readFileSync(htmlPath, 'utf8');
      expect(htmlContent).toContain('<div id="desktop-wallpaper"');
      expect(htmlContent).toContain('id="desktop-wallpaper-dimmer"');
      const wpIdx = htmlContent.indexOf('id="desktop-wallpaper"');
      const dimmerIdx = htmlContent.indexOf('id="desktop-wallpaper-dimmer"');
      expect(wpIdx).toBeLessThan(dimmerIdx);
    });
  });

  describe('Docker Stacks Modal & Lifecycle', () => {
    it('initializes stack modal and handles open, tab switch, and close', async () => {
      const mockStackDetails = {
        name: 'arr',
        origin: 'dockhand',
        config_file: '/app/data/stacks/prod/arr/compose.yaml',
        compose_yaml: 'version: "3.8"\nservices:\n  radarr:\n    image: radarr\n',
        env_content: 'PUID=1000\nPGID=1000\n',
        has_real_file: true,
        location_type: 'dockhand',
        running_count: 1,
        total_count: 1,
        status: 'running',
        containers: [
          {
            id: '1234567890ab',
            name: 'arr_radarr',
            service: 'radarr',
            state: 'running',
            status: 'Up 4 hours',
            image: 'lscr.io/linuxserver/radarr:latest',
          },
        ],
      };

      vi.spyOn(api, 'get').mockResolvedValue(mockStackDetails);

      initStackModal();

      await openStackModal('arr');

      const overlay = document.getElementById('stack-inspector-overlay');
      expect(overlay.style.display).toBe('flex');
      expect(document.getElementById('stack-header-title').textContent).toBe('Stack: arr');
      expect(document.getElementById('stack-compose-editor').value).toBe(mockStackDetails.compose_yaml);
      expect(document.getElementById('stack-env-editor').value).toBe(mockStackDetails.env_content);

      // Tab switching
      switchStackTab('env');
      expect(document.getElementById('stack-pane-env').style.display).toBe('flex');
      expect(document.getElementById('stack-pane-compose').style.display).toBe('none');

      switchStackTab('services');
      expect(document.getElementById('stack-pane-services').style.display).toBe('flex');
      const servicesList = document.getElementById('stack-services-list');
      expect(servicesList.innerHTML).toContain('radarr');
      expect(servicesList.innerHTML).toContain('1234567890ab');

      // Close modal
      closeStackModal();
      expect(overlay.style.display).toBe('none');
    });


    it('saves stack configuration successfully', async () => {
      const mockStackDetails = {
        name: 'immich',
        origin: 'compose',
        config_file: '/mnt/user/appdata/immich/compose.yaml',
        compose_yaml: 'services:\n  server:\n    image: immich-server\n',
        env_content: 'TZ=America/New_York\n',
        running_count: 0,
        total_count: 0,
        status: 'stopped',
        containers: [],
      };

      vi.spyOn(api, 'get').mockResolvedValue(mockStackDetails);
      const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
        success: true,
        message: 'Saved successfully',
      });

      initStackModal();
      await openStackModal('immich');

      const composeTextarea = document.getElementById('stack-compose-editor');
      composeTextarea.value = 'services:\n  server:\n    image: immich-server:v1.100\n';

      const saveBtn = document.getElementById('stack-save-btn');
      saveBtn.click();

      expect(postSpy).toHaveBeenCalledWith(
        '/api/docker/stacks/immich/save',
        {
          compose_yaml: 'services:\n  server:\n    image: immich-server:v1.100\n',
          env_content: 'TZ=America/New_York\n',
        }
      );
    });

    it('triggers stack action (e.g. restart)', async () => {
      const mockStackDetails = {
        name: 'syncthing',
        origin: 'compose',
        config_file: '/mnt/user/appdata/syncthing/compose.yaml',
        compose_yaml: 'services:\n  syncthing:\n    image: syncthing\n',
        env_content: '',
        running_count: 1,
        total_count: 1,
        status: 'running',
        containers: [{ id: 'abc', name: 'syncthing', service: 'syncthing', state: 'running' }],
      };

      vi.spyOn(api, 'get').mockResolvedValue(mockStackDetails);
      const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
        success: true,
        action: 'restart',
      });

      initStackModal();
      await openStackModal('syncthing');

      const restartBtn = document.getElementById('stack-action-restart');
      restartBtn.click();

      expect(postSpy).toHaveBeenCalledWith(
        '/api/docker/stacks/syncthing/action',
        { action: 'restart' }
      );
    });
  });
});
