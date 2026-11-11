/**
 * Flags compose settings that give a container power over the host (AI-22).
 * Line-based on purpose: it has to work on half-written YAML pasted from a chat.
 * Returns [{ level: 'danger' | 'warn', line, text }], text in the reader's language (SET-14).
 */
import { t } from './i18n.js';

/** @type {Array<[RegExp, string, string, string]>} */
const RULES = [
  [/^\s*privileged:\s*(true|yes|"true"|'true')\s*$/i, 'danger', 'compose_risk.privileged', 'privileged: full access to the host'],
  [/docker\.sock/i, 'danger', 'compose_risk.docker_sock', 'mounts the Docker socket: the container can control every container and the host'],
  [/^\s*pid:\s*["']?host/i, 'danger', 'compose_risk.pid_host', 'pid: host: sees and can signal every process on the host'],
  [/^\s*network_mode:\s*["']?host/i, 'warn', 'compose_risk.network_host', 'network_mode: host: shares the host network, its ports skip Docker isolation'],
  [/^\s*ipc:\s*["']?host/i, 'warn', 'compose_risk.ipc_host', 'ipc: host: shares host memory segments'],
  [/^\s*(-\s*)?["']?(SYS_ADMIN|ALL|SYS_MODULE|SYS_PTRACE|SYS_RAWIO|DAC_READ_SEARCH)["']?\s*$/i, 'danger', 'compose_risk.cap_escape', 'adds a capability that allows escaping the container'],
  [/^\s*(-\s*)?["']?(NET_ADMIN|NET_RAW)["']?\s*$/i, 'warn', 'compose_risk.cap_net', 'adds a network capability (NET_ADMIN/NET_RAW)'],
  [/(apparmor|seccomp|label)[:=]\s*["']?(unconfined|disable)/i, 'danger', 'compose_risk.profile_off', 'turns off a security profile'],
  [/^\s*-\s*["']?\/(:|["'\s]|$)/, 'danger', 'compose_risk.root_fs', 'mounts the whole host filesystem'],
  [/^\s*-\s*["']?\/(etc|root|boot|proc|sys|dev|usr|var\/lib\/docker)(\/[^:]*)?:/i, 'danger', 'compose_risk.system_folder', 'mounts a host system folder'],
  [/^\s*devices:\s*$/i, 'warn', 'compose_risk.devices', 'passes host devices into the container'],
  [/^\s*userns_mode:\s*["']?host/i, 'warn', 'compose_risk.userns_host', 'userns_mode: host: turns off user-namespace remapping'],
];

export function lintCompose(yaml) {
  const findings = [];
  String(yaml || '')
    .split(/\r?\n/)
    .forEach((raw, idx) => {
      const line = raw.replace(/\s+#.*$/, '');
      if (/^\s*#/.test(raw)) return;
      for (const [re, level, key, text] of RULES) {
        if (re.test(line)) findings.push({ level, line: idx + 1, text: t(key, text) });
      }
    });
  return findings;
}

export function composeRiskSummary(findings) {
  return findings.map((f) => t('compose_risk.line', 'Line {line}: {text}', { line: f.line, text: f.text })).join('\n');
}
