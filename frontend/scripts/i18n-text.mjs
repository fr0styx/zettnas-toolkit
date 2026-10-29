// Text a person reads between tags, in markup and in JS templates (UX-21). The older checks see
// attributes and textContent writes; this one sees `<b>Save</b>`, `>${n} files selected<` and
// ALL-CAPS labels too. Used by i18n-lint.mjs, which keeps a per-file baseline that only goes down.
import * as acorn from 'acorn';
import { parse as parseHtml } from 'parse5';

// Names that read the same in every language
const SAME_EVERYWHERE = new Set([
  'ZettNAS', 'Unraid', 'Docker', 'Immich', 'Ollama', 'OpenVINO', 'WebDAV', 'Tailscale', 'Jellyfin',
  'Plex', 'Nextcloud', 'Syncthing', 'Samba', 'iSCSI', 'Btrfs', 'NVMe', 'SMART', 'Linux', 'Windows',
  'macOS', 'iOS', 'Android', 'GitHub', 'Apprise', 'Telegram', 'Discord', 'Gotify', 'ntfy', 'Pushover',
  'Wi-Fi', 'Ethernet', 'Bluetooth', 'QEMU', 'OK', 'Spotlight', 'Restic', 'Borg', 'rclone', 'rsync',
]);
const PH = '\u0000'; // where a ${...} was

export function readable(raw) {
  const v = raw.replace(/&nbsp;|&#160;/g, ' ').replace(/&[a-z]+;|&#\d+;/g, ' ').replace(/\s+/g, ' ').trim();
  const words = v.replaceAll(PH, ' ').trim();
  if (!/[A-Za-z]{2}/.test(words)) return false;
  if (/:\/\/|^[\w.+-]+@[\w.-]+$|^\/|^~|^[\w.-]+\.(?:conf|json|ya?ml|sh|py|js|local|lan|html|css)$/.test(words)) return false;
  if (/^e\.g\.?\s*\S+$/.test(words)) return false;
  if (SAME_EVERYWHERE.has(words)) return false;
  const bare = words.split(' ').filter((w) => /[A-Za-z]/.test(w));
  if (bare.length === 1) {
    const w = bare[0].replace(/[^\w-]/g, '');
    if (/^[a-z0-9_.:-]+$/.test(w)) return false; // an id, a unit, a file name
    if (/^[A-Z0-9-]{2,6}$/.test(w)) return false; // an acronym: CPU, RAID, 2FA, SMB
    if (/^\d+(?:[.,]\d+)?\s?[A-Za-z]{1,3}\/?s?$/.test(w)) return false; // 12 GB, 5 ms
    if (SAME_EVERYWHERE.has(w)) return false;
  }
  if (/^[\d\s.,:%xX×/+()-]+[A-Za-z]{0,4}$/.test(words)) return false;
  if (/^[^A-Za-z]*(?:[A-Z]{1,6}|[a-z]{1,3})[^A-Za-z]*$/.test(words)) return false; // "x", "°C", "(GB)"
  return true;
}

function htmlTextNodes(src, lines = false) {
  const out = [];
  const visit = (node, translated) => {
    const attrs = Object.fromEntries((node.attrs || []).map((a) => [a.name, a.value]));
    const here = translated || 'data-i18n' in attrs || 'data-i18n-html' in attrs || 'data-sample' in attrs
      || 'translate' in attrs && attrs.translate === 'no';
    if (node.nodeName === 'script' || node.nodeName === 'style' || node.nodeName === 'code' || node.nodeName === 'pre'
      || node.nodeName === 'kbd' || node.nodeName === 'svg') return;
    for (const child of node.childNodes || (node.content ? node.content.childNodes : [])) {
      if (child.nodeName === '#text') {
        if (!here && readable(child.value)) {
          out.push(lines ? `${child.sourceCodeLocation?.startLine}: ${child.value.trim()}` : child.value.trim());
        }
      } else visit(child, here);
    }
    if (node.content) visit(node.content, here);
  };
  visit(parseHtml(src, { sourceCodeLocationInfo: lines }), false);
  return out;
}

// The text between tags in a piece of markup that may have ${} holes in it
function markupText(markup) {
  if (!/<[a-z/!]/i.test(markup)) return [];
  markup = markup.replace(/<!--[\s\S]*?(?:-->|$)/g, ' ');
  const out = [];
  // a tag that says it is translated, or code-like content, hides its text
  const re = /<(\/?)([a-zA-Z][\w-]*)([^<>]*)>|([^<>]+)/g;
  const stack = [];
  let m;
  while ((m = re.exec(markup))) {
    if (m[2]) {
      const name = m[2].toLowerCase();
      if (m[1]) {
        const i = stack.map((s) => s.name).lastIndexOf(name);
        if (i >= 0) stack.length = i;
      } else if (!/\/\s*$/.test(m[3]) && !['br', 'img', 'input', 'hr', 'use', 'meta', 'link', 'source', 'wbr', 'path', 'circle', 'rect'].includes(name)) {
        stack.push({ name, quiet: /\sdata-i18n(?:-html)?=|\sdata-sample\b|translate="no"/.test(m[3]) || ['code', 'pre', 'kbd', 'script', 'style', 'svg'].includes(name) });
      }
    } else if (m[4] && !stack.some((s) => s.quiet) && !/=\s*"|^\s*"|"\s*$/.test(m[4]) && readable(m[4])) {
      // (a piece of a tag cut by string concatenation, like `" title="` + x, is not text)
      // text only before the first tag of a string can be a tail of something outside; still text
      out.push(m[4].replaceAll(PH, '${…}').trim());
    }
  }
  return out;
}

function jsTextNodes(src) {
  const out = [];
  let ast;
  try {
    ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', allowHashBang: true });
  } catch {
    return out;
  }
  const walk = (node, parent) => {
    if (!node || typeof node.type !== 'string') return;
    if (node.type === 'TemplateLiteral') {
      out.push(...markupText(node.quasis.map((q) => q.value.cooked ?? q.value.raw).join(PH)));
    } else if (node.type === 'Literal' && typeof node.value === 'string' && /<[a-z/]/i.test(node.value)) {
      out.push(...markupText(node.value));
    }
    for (const key of Object.keys(node)) {
      if (key === 'loc' || key === 'start' || key === 'end') continue;
      const v = node[key];
      if (Array.isArray(v)) v.forEach((c) => walk(c, node));
      else if (v && typeof v.type === 'string') walk(v, node);
    }
  };
  walk(ast, null);
  return out;
}

export function textNodes(src, file, lines = false) {
  return file.endsWith('.html') ? htmlTextNodes(src, lines) : jsTextNodes(src);
}
