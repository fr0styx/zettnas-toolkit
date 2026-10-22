/**
 * Flags compose settings that give a container power over the host (AI-22).
 * Line-based on purpose: it has to work on half-written YAML pasted from a chat.
 * Returns [{ level: 'danger' | 'warn', line, text }].
 */
const RULES = [
  [/^\s*privileged:\s*(true|yes|"true"|'true')\s*$/i, 'danger', 'privileged: full access to the host'],
  [/docker\.sock/i, 'danger', 'mounts the Docker socket: the container can control every container and the host'],
  [/^\s*pid:\s*["']?host/i, 'danger', 'pid: host: sees and can signal every process on the host'],
  [/^\s*network_mode:\s*["']?host/i, 'warn', 'network_mode: host: shares the host network, its ports skip Docker isolation'],
  [/^\s*ipc:\s*["']?host/i, 'warn', 'ipc: host: shares host memory segments'],
  [/^\s*(-\s*)?["']?(SYS_ADMIN|ALL|SYS_MODULE|SYS_PTRACE|SYS_RAWIO|DAC_READ_SEARCH)["']?\s*$/i, 'danger', 'adds a capability that allows escaping the container'],
  [/^\s*(-\s*)?["']?(NET_ADMIN|NET_RAW)["']?\s*$/i, 'warn', 'adds a network capability (NET_ADMIN/NET_RAW)'],
  [/(apparmor|seccomp|label)[:=]\s*["']?(unconfined|disable)/i, 'danger', 'turns off a security profile'],
  [/^\s*-\s*["']?\/(:|["'\s]|$)/, 'danger', 'mounts the whole host filesystem'],
  [/^\s*-\s*["']?\/(etc|root|boot|proc|sys|dev|usr|var\/lib\/docker)(\/[^:]*)?:/i, 'danger', 'mounts a host system folder'],
  [/^\s*devices:\s*$/i, 'warn', 'passes host devices into the container'],
  [/^\s*userns_mode:\s*["']?host/i, 'warn', 'userns_mode: host: turns off user-namespace remapping'],
];

export function lintCompose(yaml) {
  const findings = [];
  String(yaml || '')
    .split(/\r?\n/)
    .forEach((raw, idx) => {
      const line = raw.replace(/\s+#.*$/, '');
      if (/^\s*#/.test(raw)) return;
      for (const [re, level, text] of RULES) {
        if (re.test(line)) findings.push({ level, line: idx + 1, text });
      }
    });
  return findings;
}

export function composeRiskSummary(findings) {
  return findings.map((f) => `Line ${f.line}: ${f.text}`).join('\n');
}
