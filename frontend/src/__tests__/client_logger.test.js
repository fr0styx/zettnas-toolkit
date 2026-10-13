import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  scrubClientString,
  pushLogEntry,
  getClientLogs,
  clearClientLogs,
  getWebGLGPUInfo,
  collectClientEnvironment,
  initClientLogger,
} from '../client-logger.js';

describe('client-logger.js Observability Engine', () => {
  beforeEach(() => {
    clearClientLogs();
    vi.restoreAllMocks();
  });

  describe('scrubClientString', () => {
    it('redacts ZettNAS session tokens zat_...', () => {
      const input = 'Request failed with auth header zat_abcdef1234567890abcdef123456';
      const output = scrubClientString(input);
      expect(output).not.toContain('zat_abcdef1234567890abcdef123456');
      expect(output).toContain('***REDACTED***');
    });

    it('redacts Bearer tokens', () => {
      const input = 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token.signature';
      const output = scrubClientString(input);
      expect(output).not.toContain('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9');
      expect(output).toContain('***REDACTED***');
    });

    it('redacts password key-value parameters', () => {
      const input = 'Connecting to db with password=superSecretPassword123 and user=admin';
      const output = scrubClientString(input);
      expect(output).not.toContain('superSecretPassword123');
      expect(output).toContain('password=***REDACTED***');
    });

    it('safely handles non-string inputs', () => {
      expect(scrubClientString(12345)).toBe('12345');
      expect(scrubClientString(null)).toBe('null');
      expect(scrubClientString(undefined)).toBe('undefined');
    });
  });

  describe('pushLogEntry and circular ring buffer', () => {
    it('records entries and limits capacity to 250 items', () => {
      for (let i = 0; i < 260; i++) {
        pushLogEntry('info', `Message ${i}`);
      }
      const logs = getClientLogs();
      expect(logs.length).toBe(250);
      expect(logs[0].message).toBe('Message 10');
      expect(logs[249].message).toBe('Message 259');
    });

    it('clears logs properly', () => {
      pushLogEntry('error', 'Critical failure');
      expect(getClientLogs().length).toBe(1);
      clearClientLogs();
      expect(getClientLogs().length).toBe(0);
    });
  });

  describe('collectClientEnvironment and GPU Probing', () => {
    it('gathers client environment details without crashing', () => {
      const env = collectClientEnvironment();
      expect(env).toBeDefined();
      expect(env.browser).toBeDefined();
      expect(env.screen_geometry).toBeDefined();
      expect(env.desktop_runtime_state).toBeDefined();
      expect(env.gpu_telemetry).toBeDefined();
    });

    it('probes WebGL GPU info safely', () => {
      const gpu = getWebGLGPUInfo();
      expect(gpu).toBeDefined();
      expect(typeof gpu.supported).toBe('boolean');
    });
  });

  describe('initClientLogger', () => {
    it('initializes window.__zettnasClientLogger and intercepts logs', () => {
      initClientLogger();
      expect(window.__zettnasClientLogger).toBeDefined();
      expect(typeof window.__zettnasClientLogger.getLogs).toBe('function');

      console.error('Test error message for diagnostics');
      const logs = getClientLogs();
      const errEntry = logs.find((l) => l.message.includes('Test error message for diagnostics'));
      expect(errEntry).toBeDefined();
      expect(errEntry.level).toBe('error');
    });
  });
});
