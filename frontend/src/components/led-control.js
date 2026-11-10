/**
 * Kiboto ARGB Lighting Controller
 * Manages physical and virtual lightbar effects, color hex palettes, speed, and schedule.
 */
import { api } from '../api.js';
import { initGlassTimePickers } from './time-picker.js';
import { t } from '../i18n.js';

const $ = (id) => document.getElementById(id);

/**
 * Paints a picture of the light bar: off, a colour, or an effect at the bar's speed.
 * @param {HTMLElement | null} el
 * @param {{power?: string, mode?: string, color?: string, color2?: string, brightness?: number, speed?: number}} look
 * @param {{offOpacity?: number, force?: boolean}} [opts]
 */
export function renderLightbar(el, look, opts = {}) {
  if (!el || !look) return;
  const key = JSON.stringify(look);
  if (!opts.force && el.dataset.look === key) return; // the same look: leave the animation running
  el.dataset.look = key;
  if (look.power === 'off' || Number(look.brightness) <= 0) {
    el.style.background = '#1b2c2f';
    el.style.boxShadow = 'none';
    el.style.animation = 'none';
    el.style.opacity = String(opts.offOpacity ?? 0.2);
    return;
  }
  const c1 = '#' + String(look.color || '25c2a0').replace('#', '');
  const c2 = '#' + String(look.color2 || 'ff0055').replace('#', '');
  const bri = (look.brightness ?? 25) / 100;
  const dur = Math.max(0.3, 4.0 - ((look.speed ?? 50) / 100.0) * 3.7).toFixed(2) + 's';
  const mode = look.mode || 'solid';
  let bg = c1;
  let shadow = `0 0 14px ${c1}`;
  let anim = 'none';
  let size = 'auto';
  if (mode === 'breathe') {
    shadow = `0 0 16px ${c1}`;
    anim = `barBreathe ${dur} infinite ease-in-out`;
  } else if (mode === 'flow' || mode === 'chase') {
    bg = `linear-gradient(90deg, ${c1} 0%, rgba(0,0,0,0.2) 50%, ${c1} 100%)`;
    size = '200% 100%';
    shadow = `0 0 12px ${c1}`;
    anim = `barFlow ${dur} infinite linear`;
  } else if (mode === 'gradient') {
    bg = `linear-gradient(90deg, ${c1} 0%, ${c2} 50%, ${c1} 100%)`;
    size = '200% 100%';
    anim = `barFlow ${dur} infinite linear`;
  } else if (mode === 'rainbow') {
    bg = 'linear-gradient(90deg, #ff0000, #ffff00, #00ff00, #00ffff, #0000ff, #ff00ff, #ff0000)';
    size = '200% 100%';
    shadow = '0 0 16px rgba(255,255,255,0.4)';
    anim = `barRainbow ${dur} infinite linear`;
  } else if (mode === 'flashing') {
    anim = `barFlash ${dur} infinite steps(1)`;
  }
  el.style.background = bg;
  el.style.backgroundSize = size;
  el.style.boxShadow = shadow;
  el.style.animation = anim;
  el.style.opacity = String(Math.max(0.2, bri));
}

export function initLedControl() {
  initGlassTimePickers($('tab-led') || document);
  const previewBar = $('preview-bar') || $('led-live-preview-bar');
  const previewTxt = $('preview-state-txt') || $('led-preview-mode-txt');
  const slider = $('led-slider') || $('led-brightness-slider');
  const valDisplay = $('led-val-display') || $('led-brightness-val');
  const speedSlider = $('speed-slider') || $('led-speed-slider');
  const speedValDisplay = $('speed-val-display') || $('led-speed-val');
  const powerBtn = $('btn-toggle-led') || $('led-power-btn');
  const reactiveToggle = $('reactive-toggle') || $('led-reactive-toggle');
  const ledNightToggle = $('led-night-toggle');
  const ledNightStart = $('led-night-start');
  const ledNightEnd = $('led-night-end');

  const effectBtns = document.querySelectorAll('#tab-led .effect-btn, .led-effect-btn');
  // the Custom swatch is a color-chip too, but a label around a colour input with no data-hex
  const colorChips1 = document.querySelectorAll('#tab-led .color-chip:not(.custom-picker-chip), .led-color-chip');
  const customColorPicker1 = $('custom-color-picker');
  const customChip1Label = $('custom-chip-label') || $('custom-color-chip-label');

  const colorChips2 = document.querySelectorAll('#tab-led .color-chip2:not(.custom-picker-chip), .led-sec-color-chip');
  const customColorPicker2 = $('custom-color-picker2') || $('custom-sec-color-picker');
  const customChip2Label = $('custom-chip2-label') || $('custom-sec-color-chip-label');

  const profilePills = document.querySelectorAll('#tab-led .profile-pill, .led-profile-pill');
  const speedCard = $('speed-card') || $('led-card-speed');
  const priColorCard = $('primary-color-card') || $('led-card-color');
  const secColorCard = $('secondary-color-card') || $('led-card-color2');

  let currentPower = 'on';
  let currentColor = '25c2a0';
  let currentColor2 = 'ff0055';
  let currentMode = 'solid';
  let briDebounce = null;
  let speedDebounce = null;
  let colorDebounce = null;

  function formatSpeedText(val) {
    const v = parseInt(val, 10);
    if (v <= 20) return `Slow (${v}%)`;
    if (v <= 60) return `Medium (${v}%)`;
    if (v <= 85) return `Fast (${v}%)`;
    return `Ultra Fast (${v}%)`;
  }

  function updateLivePreview() {
    const look = {
      power: currentPower,
      mode: currentMode,
      color: currentColor,
      color2: currentColor2,
      brightness: parseInt(slider ? slider.value : 25, 10),
      speed: parseInt(speedSlider ? speedSlider.value : 50, 10),
    };
    if (previewTxt) {
      previewTxt.textContent = currentPower === 'off'
        ? t('led.state_off', 'Off').toUpperCase()
        : `${t('led.state_on', 'On')} • ${t(`dr.${currentMode}`, currentMode)}`.toUpperCase();
    }
    renderLightbar(previewBar, look);
    // the console's bar shows the change at once; the next stats say what the bar really does
    renderLightbar($('virtual-chassis-lightbar'), look, { offOpacity: 0.15 });
  }

  function updateDynamicCards() {
    if (speedCard) speedCard.style.display = currentMode === 'solid' ? 'none' : 'flex';
    if (secColorCard) secColorCard.style.display = currentMode === 'gradient' ? 'flex' : 'none';
    if (priColorCard) priColorCard.style.display = currentMode === 'rainbow' ? 'none' : 'flex';
    updateLivePreview();
  }

  async function postLed(powerState) {
    updateLivePreview();
    const payload = {
      power: powerState,
      brightness: parseInt(slider ? slider.value : 25, 10),
      color: currentColor,
      color2: currentColor2,
      mode: currentMode,
      speed: parseInt(speedSlider ? speedSlider.value : 50, 10),
      reactive: reactiveToggle ? reactiveToggle.checked : true,
      night_mode: ledNightToggle ? ledNightToggle.checked : false,
      night_start: ledNightStart ? ledNightStart.value : '23:00',
      night_end: ledNightEnd ? ledNightEnd.value : '07:00'
    };
    try {
      await api.post('/api/led', payload);
      currentPower = powerState;
      if (powerBtn) powerBtn.textContent = currentPower === 'on' ? t('ledx.off', 'Turn Off') : t('ledx.on', 'Turn On');
      updateLivePreview();
    } catch (err) {
      console.warn('Failed to update LED', err);
    }
  }

  async function fetchLedState() {
    try {
      const data = await api.get('/api/led');
      currentPower = data.power || 'on';
      currentColor = (data.color || '25c2a0').replace('#', '');
      currentColor2 = (data.color2 || 'ff0055').replace('#', '');
      currentMode = data.mode || 'solid';

      if (slider) slider.value = data.brightness !== undefined ? data.brightness : 25;
      if (valDisplay && slider) valDisplay.textContent = slider.value + '%';

      if (speedSlider) speedSlider.value = data.speed !== undefined ? data.speed : 50;
      if (speedValDisplay && speedSlider) speedValDisplay.textContent = formatSpeedText(speedSlider.value);

      if (powerBtn) powerBtn.textContent = currentPower === 'on' ? t('ledx.off', 'Turn Off') : t('ledx.on', 'Turn On');
      if (reactiveToggle) reactiveToggle.checked = data.reactive !== false;
      if (ledNightToggle) ledNightToggle.checked = Boolean(data.night_mode);
      if (ledNightStart && data.night_start) ledNightStart.value = data.night_start;
      if (ledNightEnd && data.night_end) ledNightEnd.value = data.night_end;
      initGlassTimePickers($('tab-led') || document);

      effectBtns.forEach((b) => b.classList.toggle('active', b.dataset.effect === currentMode));
      colorChips1.forEach((c) => c.classList.toggle('active', c.dataset.hex.toLowerCase() === currentColor.toLowerCase()));
      colorChips2.forEach((c) => c.classList.toggle('active', c.dataset.hex.toLowerCase() === currentColor2.toLowerCase()));

      profilePills.forEach((pill) => {
        const pr = pill.dataset.profile;
        let match = false;
        if (pr === 'clean' && currentMode === 'solid' && currentColor.toLowerCase() === '25c2a0') match = true;
        else if (pr === 'cyberpunk' && currentMode === 'gradient' && currentColor.toLowerCase() === '00ffff' && currentColor2.toLowerCase() === 'ff0055') match = true;
        else if (pr === 'stealth' && currentMode === 'solid' && currentColor.toLowerCase() === '001428') match = true;
        else if (pr === 'rainbow' && currentMode === 'rainbow') match = true;
        pill.classList.toggle('active', match);
      });

      updateDynamicCards();
      updateLivePreview();
    } catch (e) {
      console.warn('Failed to load LED state', e);
    }
  }

  fetchLedState();

  profilePills.forEach((p) => {
    p.addEventListener('click', () => {
      const pr = p.dataset.profile;
      profilePills.forEach((pill) => pill.classList.toggle('active', pill === p));

      if (pr === 'clean') { currentMode = 'solid'; currentColor = '25c2a0'; if (slider) slider.value = 25; }
      else if (pr === 'cyberpunk') { currentMode = 'gradient'; currentColor = '00ffff'; currentColor2 = 'ff0055'; if (slider) slider.value = 40; if (speedSlider) speedSlider.value = 65; }
      else if (pr === 'stealth') { currentMode = 'solid'; currentColor = '001428'; if (slider) slider.value = 8; }
      else if (pr === 'rainbow') { currentMode = 'rainbow'; if (slider) slider.value = 35; if (speedSlider) speedSlider.value = 70; }
      if (valDisplay && slider) valDisplay.textContent = slider.value + '%';
      if (speedValDisplay && speedSlider) speedValDisplay.textContent = formatSpeedText(speedSlider.value);
      effectBtns.forEach((b) => b.classList.toggle('active', b.dataset.effect === currentMode));
      colorChips1.forEach((c) => c.classList.toggle('active', c.dataset.hex.toLowerCase() === currentColor.toLowerCase()));
      colorChips2.forEach((c) => c.classList.toggle('active', c.dataset.hex.toLowerCase() === currentColor2.toLowerCase()));
      updateDynamicCards();
      postLed('on');
    });
  });

  if (reactiveToggle) reactiveToggle.addEventListener('change', () => postLed(currentPower));
  if (ledNightToggle) ledNightToggle.addEventListener('change', () => postLed(currentPower));
  if (ledNightStart) ledNightStart.addEventListener('change', () => postLed(currentPower));
  if (ledNightEnd) ledNightEnd.addEventListener('change', () => postLed(currentPower));

  if (slider) {
    slider.addEventListener('input', (e) => {
      profilePills.forEach((pill) => pill.classList.remove('active'));
      if (valDisplay) valDisplay.textContent = e.target.value + '%';
      updateLivePreview();
      clearTimeout(briDebounce);
      briDebounce = setTimeout(() => postLed('on'), 75);
    });
  }

  if (speedSlider) {
    speedSlider.addEventListener('input', (e) => {
      profilePills.forEach((pill) => pill.classList.remove('active'));
      if (speedValDisplay) speedValDisplay.textContent = formatSpeedText(e.target.value);
      updateLivePreview();
      clearTimeout(speedDebounce);
      speedDebounce = setTimeout(() => postLed('on'), 75);
    });
  }

  effectBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      profilePills.forEach((pill) => pill.classList.remove('active'));
      effectBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.effect;
      updateDynamicCards();
      postLed('on');
    });
  });

  colorChips1.forEach((chip) => {
    chip.addEventListener('click', () => {
      profilePills.forEach((pill) => pill.classList.remove('active'));
      colorChips1.forEach((c) => c.classList.remove('active'));
      if (customChip1Label) customChip1Label.classList.remove('active');
      chip.classList.add('active');
      currentColor = chip.dataset.hex;
      postLed('on');
    });
  });

  if (customColorPicker1) {
    customColorPicker1.addEventListener('input', (e) => {
      profilePills.forEach((pill) => pill.classList.remove('active'));
      colorChips1.forEach((c) => c.classList.remove('active'));
      if (customChip1Label) customChip1Label.classList.add('active');
      currentColor = e.target.value.replace('#', '');
      clearTimeout(colorDebounce);
      colorDebounce = setTimeout(() => postLed('on'), 75);
    });
  }

  colorChips2.forEach((chip) => {
    chip.addEventListener('click', () => {
      profilePills.forEach((pill) => pill.classList.remove('active'));
      colorChips2.forEach((c) => c.classList.remove('active'));
      if (customChip2Label) customChip2Label.classList.remove('active');
      chip.classList.add('active');
      currentColor2 = chip.dataset.hex;
      postLed('on');
    });
  });

  if (customColorPicker2) {
    customColorPicker2.addEventListener('input', (e) => {
      profilePills.forEach((pill) => pill.classList.remove('active'));
      colorChips2.forEach((c) => c.classList.remove('active'));
      if (customChip2Label) customChip2Label.classList.add('active');
      currentColor2 = e.target.value.replace('#', '');
      clearTimeout(colorDebounce);
      colorDebounce = setTimeout(() => postLed('on'), 75);
    });
  }

  if (powerBtn) {
    powerBtn.addEventListener('click', () => {
      postLed(currentPower === 'on' ? 'off' : 'on');
    });
  }
}
