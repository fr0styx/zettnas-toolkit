/**
 * ZettNAS Client-Side Observability & Diagnostics Logger
 * 
 * Captures browser console warnings/errors, unhandled exceptions, and runtime
 * environment metrics into an in-memory circular ring buffer for inclusion in the
 * System Observability & Diagnostics Bundle.
 */

const MAX_LOG_ENTRIES = 250;
const logRingBuffer = [];

// Sensitive token & credential scrubbers
const SCRUB_PATTERNS = [
  /zat_[a-zA-Z0-9_\-]{16,}/g,
  /Bearer\s+[a-zA-Z0-9_\-\.]+/gi,
  /Basic\s+[a-zA-Z0-9+/=]{8,}/gi,
  /(password|passwd|token|secret|key|auth|api_key)=([^&\s"']+)/gi,
  /"(password|passwd|token|secret|key|auth|api_key)":\s*"([^"]+)"/gi,
];

export function scrubClientString(str) {
  if (typeof str !== 'string') {
    try {
      str = String(str);
    } catch (e) {
      return '[Unstringifiable Object]';
    }
  }
  let sanitized = str;
  sanitized = sanitized.replace(/zat_[a-zA-Z0-9_\-]{16,}/g, 'zat_***REDACTED***');
  sanitized = sanitized.replace(/Bearer\s+[a-zA-Z0-9_\-\.]+/gi, 'Bearer ***REDACTED***');
  sanitized = sanitized.replace(/Basic\s+[a-zA-Z0-9+/=]{8,}/gi, 'Basic ***REDACTED***');
  sanitized = sanitized.replace(/(password|passwd|token|secret|key|auth|api_key)=([^&\s"']+)/gi, '$1=***REDACTED***');
  sanitized = sanitized.replace(/"(password|passwd|token|secret|key|auth|api_key)":\s*"([^"]+)"/gi, '"$1":"***REDACTED***"');
  return sanitized;
}

export function pushLogEntry(level, message, extra = {}) {
  const sanitizedMessage = scrubClientString(message);
  const entry = {
    ts: new Date().toISOString(),
    level: level || 'info',
    message: sanitizedMessage,
    ...extra,
  };
  if (entry.stack && typeof entry.stack === 'string') {
    entry.stack = scrubClientString(entry.stack);
  }

  logRingBuffer.push(entry);
  if (logRingBuffer.length > MAX_LOG_ENTRIES) {
    logRingBuffer.shift();
  }
}

export function getClientLogs() {
  return [...logRingBuffer];
}

export function clearClientLogs() {
  logRingBuffer.length = 0;
}

/**
 * Probes WebGL for hardware acceleration and GPU unmasked vendor/renderer.
 */
export function getWebGLGPUInfo() {
  if (typeof document === 'undefined') return { error: 'No DOM environment' };

  try {
    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) {
      return {
        supported: false,
        hardware_accelerated: false,
        vendor: 'Unavailable',
        renderer: 'None (WebGL unsupported or disabled)',
      };
    }

    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
    let vendor = 'Generic';
    let renderer = 'Generic WebGL';

    if (debugInfo) {
      vendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) || vendor;
      renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || renderer;
    } else {
      vendor = gl.getParameter(gl.VENDOR) || vendor;
      renderer = gl.getParameter(gl.RENDERER) || renderer;
    }

    // Detect software rasterization fallbacks (SwiftShader, llvmpipe, softpipe, Microsoft Basic Render)
    const isSoftware = /swiftshader|llvmpipe|softpipe|software|mesa|basic render/i.test(renderer);

    // Clean up WebGL context if lose_context extension is supported
    const loseContext = gl.getExtension('WEBGL_lose_context');
    if (loseContext) {
      loseContext.loseContext();
    }

    return {
      supported: true,
      hardware_accelerated: !isSoftware,
      vendor: String(vendor),
      renderer: String(renderer),
      is_software_rasterizer: isSoftware,
    };
  } catch (err) {
    return {
      supported: false,
      hardware_accelerated: false,
      error: scrubClientString(err?.message || 'WebGL check failed'),
    };
  }
}

/**
 * Collects complete client-side browser, viewport, GPU, and desktop environment.
 */
export function collectClientEnvironment() {
  if (typeof window === 'undefined') {
    return { environment: 'Server/Non-browser' };
  }

  const nav = window.navigator || {};
  const screen = window.screen || {};
  const docEl = document.documentElement;

  // Window inventory
  let openWindows = [];
  let activeWindowId = null;
  if (window.DockManager && window.DockManager.windows) {
    activeWindowId = window.DockManager.activeId || null;
    openWindows = Object.keys(window.DockManager.windows).filter(
      (id) => !window.DockManager.windows[id].closed
    );
  }

  // Network connection telemetry
  let connInfo = null;
  if (nav.connection) {
    connInfo = {
      effective_type: nav.connection.effectiveType || null,
      downlink_mbps: nav.connection.downlink || null,
      rtt_ms: nav.connection.rtt || null,
      save_data: !!nav.connection.saveData,
    };
  }

  // Readability / Theme variables
  let theme = 'default';
  let accent = 'default';
  let dimVal = '0.15';
  let blurVal = '0px';
  try {
    theme = docEl?.getAttribute('data-theme') || localStorage.getItem('zettnas_theme') || 'default';
    accent = localStorage.getItem('zettnas_accent_color') || 'default';
    dimVal = docEl?.style?.getPropertyValue('--wallpaper-dim') || '0.15';
    blurVal = docEl?.style?.getPropertyValue('--wallpaper-blur') || '0px';
  } catch (e) {}

  return {
    timestamp: new Date().toISOString(),
    browser: {
      user_agent: nav.userAgent || 'Unknown',
      platform: nav.platform || 'Unknown',
      vendor: nav.vendor || 'Unknown',
      language: nav.language || 'en',
      languages: nav.languages || [nav.language || 'en'],
      cookie_enabled: !!nav.cookieEnabled,
      on_line: nav.onLine !== undefined ? nav.onLine : true,
    },
    screen_geometry: {
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      screen_width: screen.width,
      screen_height: screen.height,
      avail_width: screen.availWidth,
      avail_height: screen.availHeight,
      device_pixel_ratio: window.devicePixelRatio || 1,
      color_depth: screen.colorDepth || 24,
      orientation: screen.orientation?.type || 'landscape-primary',
    },
    hardware_concurrency: nav.hardwareConcurrency || null,
    device_memory_gb: nav.deviceMemory || null,
    gpu_telemetry: getWebGLGPUInfo(),
    network_connection: connInfo,
    desktop_runtime_state: {
      theme,
      accent,
      wallpaper_dim: dimVal,
      wallpaper_blur: blurVal,
      has_wallpaper_blur_class: docEl?.classList?.contains('has-wallpaper-blur') || false,
      active_window_id: activeWindowId,
      open_windows: openWindows,
      open_window_count: openWindows.length,
      current_url_path: window.location.pathname,
    },
  };
}

let isInitialized = false;

/**
 * Initializes the client-side logger and intercepts console warnings, errors,
 * and uncaught exceptions.
 */
export function initClientLogger() {
  if (isInitialized || typeof window === 'undefined') return;
  isInitialized = true;

  // Intercept console.error
  const originalConsoleError = console.error;
  console.error = function (...args) {
    try {
      const msg = args.map((a) => (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' ');
      pushLogEntry('error', msg, { source: 'console.error' });
    } catch (e) {}
    originalConsoleError.apply(console, args);
  };

  // Intercept console.warn
  const originalConsoleWarn = console.warn;
  console.warn = function (...args) {
    try {
      const msg = args.map((a) => (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' ');
      pushLogEntry('warn', msg, { source: 'console.warn' });
    } catch (e) {}
    originalConsoleWarn.apply(console, args);
  };

  // Intercept uncaught runtime window errors
  window.addEventListener('error', (event) => {
    try {
      pushLogEntry('uncaught_error', event.message || 'Unknown Error', {
        source: event.filename ? `${event.filename}:${event.lineno}:${event.colno}` : 'window.onerror',
        stack: event.error?.stack || null,
      });
    } catch (e) {}
  });

  // Intercept unhandled promise rejections
  window.addEventListener('unhandledrejection', (event) => {
    try {
      const reason = event.reason;
      const msg = reason?.message || (typeof reason === 'string' ? reason : JSON.stringify(reason) || 'Unhandled Promise Rejection');
      pushLogEntry('unhandled_rejection', msg, {
        source: 'unhandledrejection',
        stack: reason?.stack || null,
      });
    } catch (e) {}
  });

  // Attach global accessor for debug / diagnostic packaging
  window.__zettnasClientLogger = {
    getLogs: getClientLogs,
    clearLogs: clearClientLogs,
    getEnvironment: collectClientEnvironment,
  };
}
