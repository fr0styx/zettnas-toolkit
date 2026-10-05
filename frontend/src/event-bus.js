/**
 * ZettNAS Toolkit Reactive Event Bus
 * Extends EventTarget with ergonomic on/off/emit helper methods.
 */
class EventBus extends EventTarget {
  constructor() {
    super();
    this._handlerMap = new Map();
  }

  on(event, handler) {
    if (typeof handler !== 'function') return;
    const wrapped = (e) => handler(e.detail, e);
    let handlers = this._handlerMap.get(handler);
    if (!handlers) {
      handlers = new Map();
      this._handlerMap.set(handler, handlers);
    }
    handlers.set(event, wrapped);
    this.addEventListener(event, wrapped);
    return () => this.off(event, handler);
  }

  off(event, handler) {
    const handlers = this._handlerMap.get(handler);
    if (handlers && handlers.has(event)) {
      const wrapped = handlers.get(event);
      this.removeEventListener(event, wrapped);
      handlers.delete(event);
      if (handlers.size === 0) {
        this._handlerMap.delete(handler);
      }
    } else {
      this.removeEventListener(event, handler);
    }
  }

  once(event, handler) {
    if (typeof handler !== 'function') return;
    const wrapped = (e) => {
      this.off(event, handler);
      handler(e.detail, e);
    };
    this.on(event, wrapped);
  }

  emit(event, detail = null) {
    this.dispatchEvent(new CustomEvent(event, { detail }));
  }
}

export const ZettEventBus = new EventBus();
export default ZettEventBus;
