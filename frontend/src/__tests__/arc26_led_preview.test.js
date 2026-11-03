/** NUX-20: the LED preview's state line in the reader's language. */
import { describe, it, expect, vi, afterEach } from 'vitest';

const led = { power: 'off', mode: 'breathe' };
vi.mock('../api.js', () => ({ api: { get: vi.fn(async (url) => (url === '/api/led' ? { ...led } : {})), post: vi.fn(async () => ({})) } }));

const { setLanguage, t } = await import('../i18n.js');
const { initLedControl } = await import('../components/led-control.js');
const txt = () => document.getElementById('preview-state-txt').textContent;

describe('LED preview state', () => {
  afterEach(async () => {
    await setLanguage('en');
  });

  it('says off, or on with the effect, in the reader language', async () => {
    document.body.innerHTML = '<span id="preview-state-txt"></span><div id="led-preview-bar"></div>';
    initLedControl();
    await vi.waitFor(() => expect(txt()).toBe('OFF'));

    led.power = 'on';
    await setLanguage('de');
    document.body.innerHTML = '<span id="preview-state-txt"></span><div id="led-preview-bar"></div>';
    initLedControl();
    await vi.waitFor(() => expect(txt()).toBe(`AN • ${t('dr.breathe', 'Breathe').toUpperCase()}`));
  });

  it('works on a page without the preview line', async () => {
    const { api } = await import('../api.js');
    for (const power of ['off', 'on']) {
      led.power = power;
      document.body.innerHTML = '<div id="led-preview-bar"></div>';
      api.get.mockClear();
      initLedControl();
      await vi.waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/led'));
      await new Promise((r) => setTimeout(r, 0));
    }
    expect(document.getElementById('preview-state-txt')).toBeNull();
  });
});
