/**
 * Images Module — A1111 Stable Diffusion image generation tool.
 */

import { t as _t } from './i18n.js';
import { makeWindowDraggable } from './windowDrag.js';
import * as Modals from './modalManager.js';

const API_BASE = window.location.origin;
let _generating = false;

function _el(id) { return document.getElementById(id); }

function _makeDraggable(content) {
  if (!content) return;
  const header = content.querySelector('.modal-header');
  if (!header) return;
  const modal = content.closest('.modal') || content;
  makeWindowDraggable(modal, { content, header });
}

export function isImagesOpen() {
  const modal = document.getElementById('images-modal');
  return !!modal && modal.parentElement && !modal.classList.contains('hidden') && !modal.classList.contains('modal-minimized');
}

export function closeImages() {
  const modal = document.getElementById('images-modal');
  if (modal) {
    const content = modal.querySelector('.modal-content');
    if (content) {
      content.classList.add('modal-closing');
      content.addEventListener('animationend', () => modal.remove(), { once: true });
      setTimeout(() => { if (modal.parentElement) modal.remove(); }, 250);
    } else {
      modal.remove();
    }
  }
  Modals.unregister('images-modal');
}

export function openImages() {
  if (Modals.isRegistered('images-modal') && Modals.isMinimized('images-modal')) {
    Modals.restore('images-modal');
    return;
  }
  const existing = document.getElementById('images-modal');
  if (existing) { existing.remove(); }

  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.id = 'images-modal';
  modal.innerHTML = `
    <div class="modal-content" style="width:560px;max-width:90vw;">
      <div class="modal-header">
        <h4>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;margin-right:6px">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
            <circle cx="10" cy="9" r="1"/><path d="M16 20l-3-4-2 3-2-2-3 5"/>
          </svg>
          Generate Image
        </h4>
        <button class="modal-close" id="images-close">&times;</button>
      </div>
      <div class="modal-body" style="padding:16px;">
        <div style="margin-bottom:12px;">
          <label style="display:block;margin-bottom:4px;font-size:12px;opacity:0.7;">Prompt</label>
          <textarea id="images-prompt" rows="3" style="width:100%;resize:vertical;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--fg);font-family:inherit;font-size:13px;" placeholder="Describe the image you want to generate..."></textarea>
        </div>
        <div style="display:flex;gap:12px;margin-bottom:12px;">
          <div style="flex:1;">
            <label style="display:block;margin-bottom:4px;font-size:12px;opacity:0.7;">Width</label>
            <select id="images-width" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--fg);">
              <option value="512">512</option>
              <option value="768">768</option>
              <option value="1024" selected>1024</option>
              <option value="1280">1280</option>
              <option value="1536">1536</option>
            </select>
          </div>
          <div style="flex:1;">
            <label style="display:block;margin-bottom:4px;font-size:12px;opacity:0.7;">Height</label>
            <select id="images-height" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--fg);">
              <option value="512">512</option>
              <option value="768" selected>768</option>
              <option value="1024">1024</option>
              <option value="1280">1280</option>
              <option value="1536">1536</option>
            </select>
          </div>
        </div>
        <details style="margin-bottom:12px;font-size:13px;">
          <summary style="cursor:pointer;opacity:0.6;">Advanced options</summary>
          <div style="margin-top:8px;display:flex;gap:12px;flex-wrap:wrap;">
            <div style="flex:1;min-width:120px;">
              <label style="display:block;margin-bottom:4px;font-size:12px;opacity:0.7;">Steps</label>
              <input type="number" id="images-steps" value="20" min="1" max="150" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--fg);">
            </div>
            <div style="flex:1;min-width:120px;">
              <label style="display:block;margin-bottom:4px;font-size:12px;opacity:0.7;">CFG Scale</label>
              <input type="number" id="images-cfg" value="7" min="1" max="30" step="0.5" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--fg);">
            </div>
            <div style="flex:1;min-width:140px;">
              <label style="display:block;margin-bottom:4px;font-size:12px;opacity:0.7;">Sampler</label>
              <select id="images-sampler" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--fg);">
                <option value="Euler a">Euler a</option>
                <option value="Euler">Euler</option>
                <option value="DPM++ 2M Karras" selected>DPM++ 2M Karras</option>
                <option value="DPM++ SDE Karras">DPM++ SDE Karras</option>
                <option value="DDIM">DDIM</option>
                <option value="UniPC">UniPC</option>
                <option value="LCM">LCM</option>
              </select>
            </div>
          </div>
          <div style="margin-top:8px;">
            <label style="display:block;margin-bottom:4px;font-size:12px;opacity:0.7;">Negative Prompt</label>
            <textarea id="images-negative" rows="2" style="width:100%;resize:vertical;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--panel);color:var(--fg);font-family:inherit;font-size:13px;" placeholder="Things to avoid..."></textarea>
          </div>
        </details>
        <button id="images-generate-btn" style="width:100%;padding:10px;border:none;border-radius:8px;background:var(--accent-primary,var(--red));color:#fff;font-size:14px;font-weight:600;cursor:pointer;">
          Generate
        </button>
        <div id="images-status" style="margin-top:8px;font-size:12px;text-align:center;opacity:0;transition:opacity 0.2s;"></div>
        <div id="images-result" style="margin-top:12px;display:none;">
          <img id="images-preview" style="width:100%;border-radius:8px;border:1px solid var(--border);cursor:pointer;" loading="lazy">
          <div style="display:flex;gap:8px;margin-top:8px;">
            <button id="images-download-btn" class="modal-btn" style="flex:1;">Download</button>
            <button id="images-retry-btn" class="modal-btn" style="flex:1;">Generate Again</button>
          </div>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
  _makeDraggable(modal.querySelector('.modal-content'));

  Modals.register('images-modal', {
    railBtnId: 'rail-images',
    sidebarBtnId: 'tool-images-btn',
    closeFn: closeImages,
    restoreFn: () => {},
  });
  Modals.injectMinimizeButton(modal, 'images-modal');

  _el('images-close').onclick = closeImages;
  _el('images-generate-btn').onclick = _doGenerate;
  _el('images-retry-btn').onclick = _doGenerate;
  _el('images-download-btn').onclick = _doDownload;

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeImages();
  });

  setTimeout(() => _el('images-prompt')?.focus(), 100);
}

async function _doGenerate() {
  if (_generating) return;
  _generating = true;

  const btn = _el('images-generate-btn');
  const status = _el('images-status');
  const result = _el('images-result');
  const preview = _el('images-preview');

  btn.textContent = 'Generating...';
  btn.style.opacity = '0.7';
  btn.disabled = true;
  result.style.display = 'none';
  status.style.opacity = '1';
  status.textContent = 'Sending request to A1111...';
  status.style.color = 'var(--fg)';

  const prompt = _el('images-prompt').value.trim();
  if (!prompt) {
    status.textContent = 'Please enter a prompt.';
    status.style.color = 'var(--accent-error, red)';
    _generating = false;
    btn.textContent = 'Generate';
    btn.style.opacity = '1';
    btn.disabled = false;
    return;
  }

  const payload = {
    prompt,
    width: parseInt(_el('images-width').value) || 1024,
    height: parseInt(_el('images-height').value) || 768,
    negative_prompt: _el('images-negative').value.trim(),
    steps: parseInt(_el('images-steps').value) || 20,
    cfg_scale: parseFloat(_el('images-cfg').value) || 7,
    sampler_name: _el('images-sampler').value,
  };

  try {
    const resp = await fetch(`${API_BASE}/api/images/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      throw new Error(err.detail || err.error || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    preview.src = data.image_url;
    result.style.display = 'block';
    status.style.opacity = '0';
    status.textContent = '';

    window.dispatchEvent(new CustomEvent('gallery-refresh'));
  } catch (err) {
    status.style.opacity = '1';
    status.textContent = `Error: ${err.message}`;
    status.style.color = 'var(--accent-error, red)';
  } finally {
    _generating = false;
    btn.textContent = 'Generate';
    btn.style.opacity = '1';
    btn.disabled = false;
  }
}

function _doDownload() {
  const preview = _el('images-preview');
  if (!preview.src) return;
  const a = document.createElement('a');
  a.href = preview.src;
  a.download = `a1111-${Date.now()}.png`;
  a.click();
}

const imagesModule = { isImagesOpen, closeImages, openImages };
export default imagesModule;
