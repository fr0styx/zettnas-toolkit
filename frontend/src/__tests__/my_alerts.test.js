import { describe, it, expect } from 'vitest';
import { myAlertsHtml } from '../components/my-alerts.js';

describe('my alerts (Batch 6)', () => {
  it('shows the person\'s choices', () => {
    document.body.innerHTML = myAlertsHtml({ ntfy_topic: 'dad-phone', email: '', events: ['ups'], min_level: 'critical' }, ['ups', 'backup']);
    expect(document.querySelector('input[name=ntfy_topic]').value).toBe('dad-phone');
    expect(document.querySelector('input[value=ups]').checked).toBe(true);
    expect(document.querySelector('input[value=backup]').checked).toBe(false);
    expect(document.querySelector('select[name=min_level]').value).toBe('critical');
  });
});
