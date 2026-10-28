import { describe, it, expect, vi } from 'vitest';

vi.mock('../components/setup-wizard.js', () => ({
  initSetupWizard: vi.fn(),
  openSetupWizard: vi.fn(),
  checkAndTriggerSetupWizard: vi.fn(),
}));

// PERF-9: what the first load leaves out, and the small pieces that stand in for it
describe('loaded when needed (PERF-9)', () => {
  it('the setup wizard loads on first use, once', async () => {
    const wiz = await import('../components/setup-wizard.js');
    const gate = await import('../components/setup-wizard-gate.js');
    expect(wiz.initSetupWizard).not.toHaveBeenCalled();
    await gate.openSetupWizard(null, true);
    await gate.checkAndTriggerSetupWizard({ security: { is_default_password: true } });
    expect(wiz.initSetupWizard).toHaveBeenCalledTimes(1);
    expect(wiz.openSetupWizard).toHaveBeenCalledWith(null, true);
    expect(wiz.checkAndTriggerSetupWizard).toHaveBeenCalledTimes(1);
  });

  it('widget names work without the widgets module, which still exports them', async () => {
    const names = await import('../components/widget-names.js');
    const el = document.createElement('div');
    el.className = 'desktop-widget';
    el.id = 'widget-drive-temp';
    const inner = document.createElement('span');
    el.appendChild(inner);
    expect(names.getWidgetKeyFromElement(inner)).toBe('drive_temp');
    expect(names.getWidgetDisplayName('nope')).toBe('Widget');
    const widgets = await import('../components/widgets.js');
    expect(widgets.getWidgetKeyFromElement).toBe(names.getWidgetKeyFromElement);
  });

  it('the signed-in person lives in session.js and users.js passes it through', async () => {
    const session = await import('../components/session.js');
    const users = await import('../components/users.js');
    session.setCurrentUser({ username: 'ana', role_id: 'share_user' });
    expect(users.getCurrentUser().username).toBe('ana');
    expect(users.formatRole).toBe(session.formatRole);
    session.setCurrentUser(null);
  });
});
