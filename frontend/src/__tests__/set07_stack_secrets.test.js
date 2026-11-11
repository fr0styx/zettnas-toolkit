/** SET-07 (S21): the stack editor hides secrets, says so, and has "Show secrets". */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../toast.js', () => ({
  showToast: vi.fn(),
  showConfirmToast: vi.fn(),
  showDangerConfirm: vi.fn(),
  showPromptToast: vi.fn(),
}));

const { api } = await import('../api.js');
const toast = await import('../toast.js');
const { initStackModal, openStackModal, toggleStackSecrets, _resetStackModalForTesting } = await import('../components/stack-modal.js');

const MASKED = { compose_yaml: 'services:\n  app:\n    environment:\n      - DB_PASSWORD=••••••••', env_content: 'TOKEN=••••••••', has_real_file: true, containers: [], secrets_shown: false };
const SHOWN = { compose_yaml: 'services:\n  app:\n    environment:\n      - DB_PASSWORD=hunter2', env_content: 'TOKEN=abc', has_real_file: true, containers: [], secrets_shown: true };
const byId = (id) => document.getElementById(id);

describe('secrets in the stack editor (SET-07)', () => {
  let get;
  beforeEach(async () => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    document.body.innerHTML = '';
    get = vi.spyOn(api, 'get').mockResolvedValue(MASKED);
    _resetStackModalForTesting();
    initStackModal();
    await openStackModal('authentik');
  });

  it('opens with secrets hidden and says how to edit them', () => {
    expect(get).toHaveBeenCalledWith('/api/docker/stacks/authentik');
    expect(byId('stack-compose-editor').value).toContain('••••••••');
    expect(byId('stack-modal-msg').textContent).toContain('Passwords and keys are hidden');
    expect(byId('stack-secrets-btn').textContent).toBe('Show secrets');
    expect(byId('stack-secrets-btn').getAttribute('aria-pressed')).toBe('false');
  });

  it('"Show secrets" loads the real values, and "Hide secrets" hides them again', async () => {
    get.mockResolvedValueOnce(SHOWN);
    await toggleStackSecrets();
    expect(get).toHaveBeenLastCalledWith('/api/docker/stacks/authentik?unmask=true');
    expect(byId('stack-compose-editor').value).toContain('DB_PASSWORD=hunter2');
    expect(byId('stack-env-editor').value).toBe('TOKEN=abc');
    expect(byId('stack-secrets-btn').textContent).toBe('Hide secrets');
    expect(byId('stack-modal-msg').textContent).not.toContain('are hidden');
    get.mockResolvedValueOnce(MASKED);
    await toggleStackSecrets();
    expect(get).toHaveBeenLastCalledWith('/api/docker/stacks/authentik');
    expect(byId('stack-compose-editor').value).toContain('••••••••');
  });

  it('does not throw away what was typed', async () => {
    byId('stack-compose-editor').value += '\n# a note';
    get.mockClear();
    await toggleStackSecrets();
    expect(get).not.toHaveBeenCalled();
    expect(toast.showToast).toHaveBeenCalledWith('Save or undo your changes first: showing or hiding secrets loads the file again.', 'warn');
    expect(byId('stack-compose-editor').value).toContain('# a note');
  });

  it('says so when the account may not see them', async () => {
    get.mockResolvedValueOnce(MASKED); // the server kept them hidden
    await toggleStackSecrets();
    expect(toast.showToast).toHaveBeenCalledWith('Your account may not see this stack’s secrets.', 'warn');
    expect(byId('stack-secrets-btn').textContent).toBe('Show secrets');
  });
});
