/**
 * One sentence at the top of Away from home: what reaches this NAS from outside (SET-24).
 * Read from GET /api/network/exposure, which asks Tailscale's and NetBird's live settings.
 * Neutral by default; amber when Tailscale needs a sign-in or its key runs out soon; red when
 * something is public that Kiboto did not turn on.
 */
import { api } from '../api.js';
import { t } from '../i18n.js';

export const LINE_ID = 'remote-exposure';
const ICON = { off: '🔒', private: '🔐', public: '🌐' };

/** "share links, 2 apps" for what Funnel publishes. */
export function publicParts(x) {
  const parts = [];
  if (x.share_links) parts.push(t('exposure.part_links', 'share links'));
  if (x.apps) parts.push(t('exposure.part_apps', '{count, plural, one {# app} other {# apps}}', { count: x.apps }));
  const other = (x.unexpected || []).length;
  if (other) parts.push(t('exposure.part_ports', '{count, plural, one {# other port} other {# other ports}}', { count: other }));
  return parts.join(', ');
}

/** When this NAS's Tailscale sign-in runs out. */
export function keyNote(days) {
  if (!days) return t('exposure.key_today', "This NAS's Tailscale sign-in runs out today.");
  return t('exposure.key', "This NAS's Tailscale sign-in runs out {count, plural, one {in # day} other {in # days}}.", { count: days });
}

/** The word, the sentence and the note under it, for a summary from the server. */
export function exposureText(x) {
  const word = {
    off: t('exposure.word_off', 'Closed'),
    private: t('exposure.word_private', 'Private'),
    public: t('exposure.word_public', 'Public'),
  }[x.level];
  let sentence;
  if (x.level === 'public') sentence = t('exposure.public', 'On the internet: {what}.', { what: publicParts(x) });
  else if (x.level === 'private' && (x.via || []).includes('tailscale')) sentence = t('exposure.private_ts', 'From outside, only devices in your Tailscale network reach this NAS.');
  else if (x.level === 'private') sentence = t('exposure.private_nb', 'From outside, only devices in your NetBird network reach this NAS.');
  else sentence = t('exposure.off', 'Through Kiboto, nothing reaches this NAS from outside.');
  const notes = [];
  if (x.reason === 'unexpected_public') notes.push(t('exposure.unexpected', 'Kiboto did not put port {ports} on the internet. Check it in Tailscale.', { ports: (x.unexpected || []).join(', ') }));
  if (x.reason === 'sign_in') notes.push(t('exposure.sign_in', 'Tailscale needs you to sign in again.'));
  if (x.reason === 'key_expiring') notes.push(keyNote(x.key_days));
  if (x.checked === false) notes.push(t('exposure.unchecked', "Kiboto couldn't ask Tailscale what is public."));
  notes.push(t('exposure.blind', "Kiboto can't see a port opened on your router, a reverse proxy or IPv6."));
  return { icon: ICON[x.level] || ICON.off, word: word || '', sentence, notes, tone: x.tone || 'neutral' };
}

/** Draws the line; on an error it stays hidden (the card below says what it can). */
export async function renderExposure(line) {
  let x;
  try {
    x = await api.get('/api/network/exposure');
  } catch {
    line.hidden = true;
    return;
  }
  const view = exposureText(x);
  line.hidden = false;
  line.className = `remote-exposure remote-exposure--${view.tone}`;
  const head = document.createElement('p');
  head.className = 'remote-exposure-head';
  const icon = document.createElement('span');
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = view.icon;
  const word = document.createElement('strong');
  word.textContent = view.word;
  head.append(icon, ' ', word, ' · ', view.sentence);
  const notes = view.notes.map((n) => {
    const p = document.createElement('p');
    p.className = 'remote-exposure-note';
    p.textContent = n;
    return p;
  });
  line.replaceChildren(head, ...notes);
}

/** Puts the line at the top of the mount, once, and draws it. */
export function installExposure(mount) {
  if (!mount) return null;
  let line = document.getElementById(LINE_ID);
  if (!line) {
    line = document.createElement('div');
    line.id = LINE_ID;
    line.setAttribute('role', 'status');
    line.hidden = true;
    mount.prepend(line);
  }
  return renderExposure(line);
}
