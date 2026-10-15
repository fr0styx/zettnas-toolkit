/**
 * ZettNAS Toolkit - Unified Command Palette & Spotlight Subsystem
 * Consolidates global fuzzy search, container commands, apps, and hardware quick-actions.
 */

export * from './spotlight.js';
export { initSpotlight as initCommandPalette } from './spotlight.js';
export { openSpotlight as openCommandPalette } from './spotlight.js';
export { closeSpotlight as closeCommandPalette } from './spotlight.js';
export { toggleSpotlight as toggleCommandPalette } from './spotlight.js';
