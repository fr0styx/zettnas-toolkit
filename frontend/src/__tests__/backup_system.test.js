import { describe, it, expect, beforeEach } from 'vitest';
import { gatherClientPreferences, applyClientPreferences } from '../components/settings.js';
import fs from 'fs';
import path from 'path';

describe('Unified Configuration Backup & Restore System', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('gatherClientPreferences collects all client desktop customizations and excludes auth and caches', () => {
    localStorage.setItem('lcd_theme', 'emerald');
    localStorage.setItem('zettnas_language', 'zh');
    localStorage.setItem('zettnas_desktop_widgets_config', '{"widgets":{"clock":true}}');
    localStorage.setItem('zettnas_dock_pinned_v1', '["terminal","files"]');
    localStorage.setItem('zettnas_win_bounds', '{"console":{"x":50,"y":50}}');
    localStorage.setItem('zettnas_token', 'session_secret_token_123');
    localStorage.setItem('zettnas_weather_cache_nyc', '{"temp":72}');
    localStorage.setItem('unrelated_key', 'should_not_be_included');

    const prefs = gatherClientPreferences();

    expect(prefs.lcd_theme).toBe('emerald');
    expect(prefs.zettnas_language).toBe('zh');
    expect(prefs.zettnas_desktop_widgets_config).toBe('{"widgets":{"clock":true}}');
    expect(prefs.zettnas_dock_pinned_v1).toBe('["terminal","files"]');
    expect(prefs.zettnas_win_bounds).toBe('{"console":{"x":50,"y":50}}');

    // Security & Cache invariants: volatile tokens and transient caches must NEVER be exported
    expect(prefs.zettnas_token).toBeUndefined();
    expect(prefs.zettnas_weather_cache_nyc).toBeUndefined();
    expect(prefs.unrelated_key).toBeUndefined();
  });

  it('applyClientPreferences safely restores preferences into localStorage without overwriting auth token', () => {
    localStorage.setItem('zettnas_token', 'active_user_session');

    applyClientPreferences({
      lcd_theme: 'amber',
      zettnas_language: 'fr',
      zettnas_dock_pinned_v1: ['console', 'storage'],
      zettnas_token: 'evil_token_overwrite'
    });

    expect(localStorage.getItem('lcd_theme')).toBe('amber');
    expect(localStorage.getItem('zettnas_language')).toBe('fr');
    expect(localStorage.getItem('zettnas_dock_pinned_v1')).toBe('["console","storage"]');
    expect(localStorage.getItem('zettnas_token')).toBe('active_user_session');
  });

  it('confirms sec-backup was removed from index.html and only Mission Control backup exists', () => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    const html = fs.readFileSync(htmlPath, 'utf8');

    // Verify duplicate stub card sec-backup was deleted
    expect(html).not.toContain('data-layout-card-id="sec-backup"');
    expect(html).not.toContain('id="btn-export-layout"');
    expect(html).not.toContain('id="file-import-layout"');

    // Verify the unified System & API backup controls exist
    expect(html).toContain('id="btn-backup-download"');
    expect(html).toContain('id="backup-upload-input"');
  });

  it('confirms sec-language was removed from drawer and placed in Mission Control Appearance', () => {
    const htmlPath = path.resolve(__dirname, '../../index.html');
    const html = fs.readFileSync(htmlPath, 'utf8');

    // Drawer card sec-language must not exist
    expect(html).not.toContain('data-layout-card-id="sec-language"');

    // Appearance tab must contain Language sub-tab button and pane
    expect(html).toContain('data-tab-target="mgmt-pane-language"');
    expect(html).toContain('id="mgmt-pane-language"');
    expect(html).toContain('id="mgmt-lang-select"');
  });
});
