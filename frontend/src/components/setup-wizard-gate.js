/**
 * The setup wizard loads only when it is needed (PERF-9): the default password is still in use,
 * someone signs in with it, or the wizard is opened from Mission Control.
 */
import { onManagementDom } from '../management-dom.js';

let _wizard = null;
let _ready = false;

export function loadSetupWizard() {
  _wizard ||= import('./setup-wizard.js').then((m) => {
    m.initSetupWizard();
    _ready = true;
    return m;
  });
  return _wizard;
}

export function checkAndTriggerSetupWizard(stats) {
  return loadSetupWizard().then((m) => m.checkAndTriggerSetupWizard(stats));
}

export function openSetupWizard(stats = null, forced = false) {
  return loadSetupWizard().then((m) => m.openSetupWizard(stats, forced));
}

/** What main.js starts: Mission Control's button, before the wizard has loaded. */
export function initSetupWizardLauncher() {
  onManagementDom(() => {
    const btn = document.getElementById('btn-launch-setup-wizard');
    // once loaded, the wizard's own handler on this button takes over
    if (btn) btn.addEventListener('click', () => _ready || openSetupWizard(null, true));
  });
}
