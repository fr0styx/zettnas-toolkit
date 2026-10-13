import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { showPromptToast } from '../toast.js';

describe('showPromptToast - Glassmorphic Prompt & Multiline Modal', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders standard text input with default values and custom icon', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    showPromptToast('Rename Item', 'Enter a new name for this item:', 'file.txt', onConfirm, onCancel, {
      icon: '🏷️',
      okText: 'Save',
      cancelText: 'Abort',
      placeholder: 'Enter filename...'
    });

    const modal = document.getElementById('confirm-toast-modal');
    const backdrop = document.getElementById('confirm-toast-backdrop');
    expect(modal).not.toBeNull();
    expect(backdrop).not.toBeNull();

    expect(modal.dataset.mode).toBe('prompt');
    expect(modal.textContent).toContain('Rename Item');
    expect(modal.textContent).toContain('🏷️');
    expect(modal.textContent).toContain('Enter a new name for this item:');

    const input = document.getElementById('prompt-toast-input');
    expect(input).not.toBeNull();
    expect(input.tagName).toBe('INPUT');
    expect(input.value).toBe('file.txt');
    expect(input.placeholder).toBe('Enter filename...');

    const okBtn = document.getElementById('confirm-toast-ok');
    expect(okBtn.textContent).toBe('Save');
    const cancelBtn = document.getElementById('confirm-toast-cancel');
    expect(cancelBtn.textContent).toBe('Abort');
  });

  it('renders multiline textarea when inputType is textarea', () => {
    const onConfirm = vi.fn();
    showPromptToast('Paste Text to Guest VM', 'Enter text string to paste:', 'echo "hello"', onConfirm, null, {
      inputType: 'textarea',
      icon: '📋',
      okText: '📋 Paste into VM',
      placeholder: 'Type or paste commands here...'
    });

    const input = document.getElementById('prompt-toast-input');
    expect(input).not.toBeNull();
    expect(input.tagName).toBe('TEXTAREA');
    expect(input.value).toBe('echo "hello"');
    expect(input.placeholder).toBe('Type or paste commands here...');

    // Regular Enter on textarea should NOT submit
    const enterEvt = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });
    input.dispatchEvent(enterEvt);
    expect(onConfirm).not.toHaveBeenCalled();

    // Ctrl+Enter on textarea should submit
    const ctrlEnterEvt = new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true });
    input.dispatchEvent(ctrlEnterEvt);
    expect(onConfirm).toHaveBeenCalledWith('echo "hello"');
  });

  it('submits textarea with Cmd+Enter on macOS', () => {
    const onConfirm = vi.fn();
    showPromptToast('Paste Code', 'Enter multiline script:', 'systemctl status', onConfirm, null, {
      inputType: 'textarea',
    });

    const input = document.getElementById('prompt-toast-input');
    const metaEnterEvt = new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true });
    input.dispatchEvent(metaEnterEvt);
    expect(onConfirm).toHaveBeenCalledWith('systemctl status');
  });

  it('submits single-line input on regular Enter key', () => {
    const onConfirm = vi.fn();
    showPromptToast('Input Name', 'Please specify a name:', 'my-vm', onConfirm);

    const input = document.getElementById('prompt-toast-input');
    input.value = 'production-server';
    const enterEvt = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });
    input.dispatchEvent(enterEvt);
    expect(onConfirm).toHaveBeenCalledWith('production-server');
  });

  it('cancels on Escape key or Cancel button click', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    showPromptToast('Input Name', 'Prompt:', '', onConfirm, onCancel);

    const escEvt = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
    document.dispatchEvent(escEvt);
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
