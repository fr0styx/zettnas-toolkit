import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { showDangerConfirm, confirmButtonFor } from '../toast.js';

const ok = () => document.getElementById('confirm-toast-ok');
const cancel = () => document.getElementById('confirm-toast-cancel');
const card = () => document.getElementById('confirm-toast-modal');
const src = (p) => readFileSync(resolve(__dirname, '..', p), 'utf8');

describe('dangerous questions are red in every language (SET-00)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it('is red and starts on Cancel when the words give no hint', () => {
    showDangerConfirm('Zum Snapshot zurückkehren', 'Der aktuelle Stand wird vorher gesichert.', vi.fn());
    vi.advanceTimersByTime(20);
    expect(card().dataset.destructive).toBe('true');
    expect(document.activeElement).toBe(cancel());
    expect(ok().style.background).toContain('kb-confirm-danger');
  });

  it('keeps the short form: a question and what to do', () => {
    const run = vi.fn();
    showDangerConfirm('Diese Sicherung vergessen?', run, null, { okText: 'Vergessen' });
    vi.advanceTimersByTime(20);
    expect(card().dataset.destructive).toBe('true');
    expect(ok().textContent).toBe('Vergessen');
    ok().click();
    expect(run).toHaveBeenCalled();
  });

  it('knows destroy and forget in the five languages', () => {
    for (const title of ['Destroy Pool', 'Pool zerstören', 'Détruire le pool', 'Destruir el pool', '销毁存储池', 'Forget', 'Vergessen', 'Oublier', 'Olvidar', '忘记']) {
      expect(confirmButtonFor(title, '').destructive, title).toBe(true);
    }
    expect(confirmButtonFor('Restart Samba', '').destructive).toBe(false);
  });

  it('marks the questions that lose or overwrite something in code, not by their words', () => {
    const marked = {
      'components/chassis-visualizer.js': ['chassis.destroy_pool', 'chassis.force_eject_title', 'chassis.disks_have_data'],
      'components/management/backup.js': ['backup.app_restore_title'],
      'components/two-way-sync.js': ['sync2.forget_confirm'],
      'components/offsite-backup.js': ['offsite.forget_confirm'],
      'components/vm/snapshots.js': ['vsn.revert_q', 'vsn.restore_q'],
    };
    for (const [file, keys] of Object.entries(marked)) {
      const code = src(file);
      for (const key of keys) {
        const at = code.indexOf(`t('${key}'`);
        expect(at, `${file}: ${key}`).toBeGreaterThan(-1);
        expect(code.slice(at - 60, at), `${file}: ${key}`).toContain('showDangerConfirm(');
      }
    }
  });
});
