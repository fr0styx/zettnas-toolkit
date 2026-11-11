import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
import { renderPracticeLine } from '../components/management/ups.js';

describe('the practice run keeps its answer on the page (SET-15, Power B4)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="ups-practice-line" class="ups-shutdown-line" hidden></div>';
  });

  it('says when it ran and who would switch the NAS off, in red when nothing would', () => {
    const line = document.getElementById('ups-practice-line');
    renderPracticeLine({ at: 1762900000, ok: false, text: null, detail: 'Nothing would switch the NAS off.' });
    expect(line.hidden).toBe(false);
    expect(line.textContent).toMatch(/^Last practice run: .+\. Nothing would switch the NAS off\.$/);
    expect(line.classList.contains('is-bad')).toBe(true);

    renderPracticeLine({ at: 1762900000, ok: true, text: null, detail: 'Kiboto shuts the server down.' });
    expect(line.classList.contains('is-bad')).toBe(false);
  });

  it('stays hidden before the first practice run', () => {
    renderPracticeLine({});
    expect(document.getElementById('ups-practice-line').hidden).toBe(true);
    renderPracticeLine(null);
    expect(document.getElementById('ups-practice-line').hidden).toBe(true);
    document.body.innerHTML = '';
    expect(() => renderPracticeLine({ at: 1 })).not.toThrow();
  });
});
