import { isCompact } from '../../device.js';
// Selecting several desktop icons with a lasso.
// Part of dock.js, split out by ARC-5.



export function initDesktopLasso() {
  if (typeof window === 'undefined' || document._desktopLassoInitialized) return;

  let isLassoing = false;
  let startX = 0, startY = 0;
  let lassoEl = null;

  document.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (isCompact()) return;
    if (
      typeof e.target?.closest === 'function' &&
      e.target.closest(
        '.smart-modal-window, .smart-modal-backdrop, .os-window, #console-window, #console-modal-overlay, ' +
        '#notif-center-panel, .notif-center-window, #management-window, .management-window, #management-modal-overlay, ' +
        '#file-manager-window, .file-manager-window, #container-inspector-window, .container-inspector-window, ' +
        '#container-inspector-overlay, #user-profile-flyout, .user-profile-flyout, .os-context-menu, ' +
        '#os-dock-container, .suite-navbar, .slide-drawer, .chassis-hero-box, .desktop-widget, ' +
        '#spotlight-palette-overlay, .window-resizer-grip, [data-window-id]'
      )
    ) {
      if (typeof e.target?.closest === 'function' && !e.target.closest('.chassis-hero-box')) {
        document.querySelectorAll('.desktop-icon-selected').forEach((el) => el.classList.remove('desktop-icon-selected'));
      }
      return;
    }

    document.querySelectorAll('.desktop-icon-selected').forEach((el) => el.classList.remove('desktop-icon-selected'));

    isLassoing = true;
    startX = e.clientX;
    startY = e.clientY;

    lassoEl = document.createElement('div');
    lassoEl.id = 'desktop-lasso-rect';
    lassoEl.style.left = `${startX}px`;
    lassoEl.style.top = `${startY}px`;
    lassoEl.style.width = '0px';
    lassoEl.style.height = '0px';
    document.body.appendChild(lassoEl);

    const onPointerMove = (mEvt) => {
      if (!isLassoing || !lassoEl) return;
      const currentX = mEvt.clientX;
      const currentY = mEvt.clientY;

      const left = Math.min(startX, currentX);
      const top = Math.min(startY, currentY);
      const width = Math.abs(currentX - startX);
      const height = Math.abs(currentY - startY);

      lassoEl.style.left = `${left}px`;
      lassoEl.style.top = `${top}px`;
      lassoEl.style.width = `${width}px`;
      lassoEl.style.height = `${height}px`;

      const lassoRect = { left, top, right: left + width, bottom: top + height };
      document.querySelectorAll('.chassis-hero-box').forEach((icon) => {
        const iRect = icon.getBoundingClientRect();
        const overlaps = !(
          lassoRect.right < iRect.left ||
          lassoRect.left > iRect.right ||
          lassoRect.bottom < iRect.top ||
          lassoRect.top > iRect.bottom
        );
        icon.classList.toggle('desktop-icon-selected', overlaps);
      });
    };

    const onPointerUp = () => {
      isLassoing = false;
      if (lassoEl) {
        lassoEl.remove();
        lassoEl = null;
      }
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', onPointerUp);
    };

    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
  });

  document._desktopLassoInitialized = true;
}
