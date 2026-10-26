// ANSI escape codes to HTML, and terminal stream handling for the serial console.
// Part of vm-manager.js, split out by ARC-5.



/**
 * Converts terminal ANSI escape sequences to styled HTML spans for serial console rendering.
 * Sanitizes HTML entities to prevent XSS and maps 3/4-bit & 256-color foreground/background colors and styles.
 * Handles both standard ANSI \x1b[33m and stripped ESC [33m sequences.
 */
export function formatAnsiToHtml(raw) {
  if (!raw) return '';

  const fgColors = {
    30: '#0f172a',
    31: '#ef4444',
    32: '#22c55e',
    33: '#f59e0b',
    34: '#3b82f6',
    35: '#a855f7',
    36: '#06b6d4',
    37: '#f8fafc',
    90: '#94a3b8',
    91: '#f87171',
    92: '#4ade80',
    93: '#fde047',
    94: '#60a5fa',
    95: '#c084fc',
    96: '#22d3ee',
    97: '#ffffff',
  };

  const bgColors = {
    40: '#000000',
    41: '#991b1b',
    42: '#166534',
    43: '#854d0e',
    44: '#1e40af',
    45: '#6b21a8',
    46: '#155e75',
    47: '#e2e8f0',
    100: '#334155',
    101: '#b91c1c',
    102: '#15803d',
    103: '#a16207',
    104: '#1d4ed8',
    105: '#7e22ce',
    106: '#0e7490',
    107: '#f1f5f9',
  };

  function get256Rgb(n) {
    if (n < 0 || n > 255) return '#ffffff';
    if (n < 8) {
      const map = ['#000000', '#ef4444', '#22c55e', '#eab308', '#3b82f6', '#a855f7', '#06b6d4', '#e2e8f0'];
      return map[n];
    }
    if (n < 16) {
      const map = ['#475569', '#f87171', '#4ade80', '#fde047', '#60a5fa', '#c084fc', '#22d3ee', '#ffffff'];
      return map[n - 8];
    }
    if (n >= 232) {
      const gray = (n - 232) * 10 + 8;
      return `rgb(${gray}, ${gray}, ${gray})`;
    }
    const r = Math.floor((n - 16) / 36) * 51;
    const g = Math.floor(((n - 16) % 36) / 6) * 51;
    const b = ((n - 16) % 6) * 51;
    return `rgb(${r}, ${g}, ${b})`;
  }

  let curFg = null;
  let curBg = null;
  let bold = false;
  let dim = false;
  let italic = false;
  let underline = false;

  let openSpan = false;
  let result = '';

  const regex = /(?:\x1b|\u001b)\[([\d;]*)m|(?:\x1b|\u001b)\[[?0-9;]*[a-zA-Z~@]|(?:\x1b|\u001b)\][^\x07\x1b]*(?:\x07|\x1b\\)|(?:\x1b|\u001b)[()#%][A-Za-z0-9]|(?:\x1b|\u001b)[=>cDEMNOZ78<]|\[(\d+(?:;\d+)*)m/g;
  let lastIndex = 0;
  let match;

  const escapeHtmlEntities = (text) => {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      // Strip any dangling unparsed escape fragments (e.g. orphan \x1b[ or lone \x1b)
      .replace(/(?:\x1b|\u001b)\[?[?0-9;]*/g, '');
  };

  while ((match = regex.exec(raw)) !== null) {
    const textChunk = raw.slice(lastIndex, match.index);
    if (textChunk) {
      result += escapeHtmlEntities(textChunk);
    }
    lastIndex = regex.lastIndex;

    const codeStr = match[1] !== undefined ? match[1] : match[2];
    if (codeStr !== undefined) {
      const codes = codeStr ? codeStr.split(';').map((n) => parseInt(n, 10)) : [0];
      for (let i = 0; i < codes.length; i++) {
        const code = codes[i];
        if (isNaN(code) || code === 0) {
          curFg = null;
          curBg = null;
          bold = false;
          dim = false;
          italic = false;
          underline = false;
        } else if (code === 1) {
          bold = true;
        } else if (code === 2) {
          dim = true;
        } else if (code === 3) {
          italic = true;
        } else if (code === 4) {
          underline = true;
        } else if (code === 22) {
          bold = false;
          dim = false;
        } else if (code === 23) {
          italic = false;
        } else if (code === 24) {
          underline = false;
        } else if (code === 39) {
          curFg = null;
        } else if (code === 49) {
          curBg = null;
        } else if (code === 38 && codes[i + 1] === 5 && codes[i + 2] !== undefined) {
          curFg = get256Rgb(codes[i + 2]);
          i += 2;
        } else if (code === 48 && codes[i + 1] === 5 && codes[i + 2] !== undefined) {
          curBg = get256Rgb(codes[i + 2]);
          i += 2;
        } else if (fgColors[code]) {
          curFg = fgColors[code];
        } else if (bgColors[code]) {
          curBg = bgColors[code];
        }
      }

      if (openSpan) {
        result += '</span>';
        openSpan = false;
      }

      const styles = [];
      if (curFg) styles.push(`color: ${curFg}`);
      if (curBg) styles.push(`background-color: ${curBg}`);
      if (bold) styles.push('font-weight: bold');
      if (dim) styles.push('opacity: 0.7');
      if (italic) styles.push('font-style: italic');
      if (underline) styles.push('text-decoration: underline');

      if (styles.length > 0) {
        result += `<span style="${styles.join('; ')}">`;
        openSpan = true;
      }
    }
  }

  const tail = raw.slice(lastIndex);
  if (tail) {
    result += escapeHtmlEntities(tail);
  }
  if (openSpan) {
    result += '</span>';
  }

  return result;
}

export const parseAnsiToHtml = formatAnsiToHtml;

/**
 * Processes incoming serial terminal stream data, applying Backspace erase sequences
 * (\x08 \x08, \x08\x1b[J, \x08\x1b[K, \x1b[D \x1b[D) and stripping terminal bell controls (\x07).
 * Accurately deletes the preceding printable character while preserving ANSI escape sequences.
 */
export function applyTerminalStream(buffer, chunk) {
  if (!chunk) return buffer || '';
  let str = (buffer || '') + chunk;

  // Fast path: if no backspace, cursor-left, bell, or escape sequences, return immediately
  if (!str.includes('\x08') && !str.includes('\x1b[D') && !str.includes('\x07') && !str.includes('\x1b[')) {
    return str;
  }

  // Strip bell characters
  str = str.replace(/\x07/g, '');

  const ansiRegex = /(?:\x1b|\u001b)\[[?0-9;]*[a-zA-Z~@]/g;
  // Matches all backspace & cursor-left erase patterns:
  // 1. \x08 \x08 (classic BS space BS)
  // 2. \x08\x1b[...[a-zA-Z~@] or \x08 \x1b[... (BS followed by ED/EL erase such as \x08\x1b[J in Alpine BusyBox ash, \x08\x1b[K in Bash/Zsh)
  // 3. \x1b[D \x1b[D or \x1b[D\x1b[... (Cursor Left erase)
  // 4. Standalone \x08 (lone BS character)
  const eraseRegex = /(?:\x08|\x1b\[D)(?: (?:\x08|\x1b\[D)|\x1b\[[?0-9;]*[a-zA-Z~@]| \x1b\[[?0-9;]*[a-zA-Z~@])?/;

  while (true) {
    const match = eraseRegex.exec(str);
    if (!match) break;

    const eraseStart = match.index;
    const eraseEnd = eraseStart + match[0].length;

    // Scan backward from eraseStart to find the visible character to delete,
    // skipping any intervening ANSI escape sequences.
    let targetIdx = -1;
    let idx = eraseStart;

    while (idx > 0) {
      const lookback = str.slice(Math.max(0, idx - 64), idx);
      const ansiMatches = [...lookback.matchAll(ansiRegex)];
      let skippedAnsi = false;
      if (ansiMatches.length > 0) {
        const lastAnsi = ansiMatches[ansiMatches.length - 1];
        if (lastAnsi.index + lastAnsi[0].length === lookback.length) {
          idx -= lastAnsi[0].length;
          skippedAnsi = true;
        }
      }
      if (skippedAnsi) continue;

      const ch = str[idx - 1];
      if (ch === '\r' || ch === '\n') {
        break;
      }
      targetIdx = idx - 1;
      break;
    }

    if (targetIdx !== -1) {
      let deleteLength = 1;
      // Check for UTF-16 surrogate pairs (e.g. emojis)
      if (targetIdx > 0) {
        const code = str.charCodeAt(targetIdx);
        if (code >= 0xdc00 && code <= 0xdfff) {
          const prevCode = str.charCodeAt(targetIdx - 1);
          if (prevCode >= 0xd800 && prevCode <= 0xdbff) {
            targetIdx -= 1;
            deleteLength = 2;
          }
        }
      }
      str = str.slice(0, targetIdx) + str.slice(targetIdx + deleteLength, eraseStart) + str.slice(eraseEnd);
    } else {
      str = str.slice(0, eraseStart) + str.slice(eraseEnd);
    }
  }

  // Strip standalone trailing clear-to-end-of-line/screen codes (\x1b[K, \x1b[J)
  str = str.replace(/(?:\x1b|\u001b)\[[?0-9;]*[JK]/g, '');

  return str;
}
