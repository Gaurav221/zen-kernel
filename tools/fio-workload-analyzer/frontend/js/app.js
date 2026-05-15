/* ── Global app core ─────────────────────────────────────────────────────── */
'use strict';

const API = (() => {
  const BASE = window.location.origin;

  async function _fetch(url, opts = {}) {
    const r = await fetch(BASE + url, {
      headers: { 'Content-Type': 'application/json', ...opts.headers },
      ...opts,
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => r.statusText);
      throw new Error(`HTTP ${r.status}: ${txt}`);
    }
    return r.json();
  }

  return {
    get:    (url)         => _fetch(url),
    post:   (url, body)   => _fetch(url, { method: 'POST', body: JSON.stringify(body) }),
    getUrl: (path)        => BASE + path,
    fetchRaw: (url)       => fetch(BASE + url),
  };
})();


const Toast = {
  show(msg, type = 'info', duration = 4000) {
    const colors = { info: 'bg-accent', success: '#a6e3a1', error: '#f38ba8', warn: '#f9e2af' };
    const div = document.createElement('div');
    div.className = 'toast show align-items-center text-white border-0 mb-2';
    div.style.cssText = `background:${colors[type]||colors.info};color:#1e1e2e!important;min-width:250px`;
    div.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${msg}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    document.getElementById('toast-container').prepend(div);
    setTimeout(() => div.remove(), duration);
  },
};


const App = {
  sessions: [],
  _clockTimer: null,

  async init() {
    this._startClock();
    await this._checkAPI();
    await this.loadDashboard();
    FioConfig.init();
    Results.init();
    LogViewer.init();
    Analysis.init();
    MLDash.init();
  },

  _startClock() {
    const el = document.getElementById('clock');
    const tick = () => { el.textContent = new Date().toLocaleTimeString(); };
    tick();
    this._clockTimer = setInterval(tick, 1000);
  },

  async _checkAPI() {
    const el = document.getElementById('api-status');
    try {
      await API.get('/api/health');
      el.innerHTML = '<i class="bi bi-circle-fill me-1"></i>Online';
      el.className = 'badge bg-success';
    } catch {
      el.innerHTML = '<i class="bi bi-circle-fill me-1"></i>Offline';
      el.className = 'badge bg-danger';
    }
  },

  async loadDashboard() {
    try {
      const data = await API.get('/api/sessions?limit=50');
      this.sessions = data.sessions || [];
      this._renderDashboardStats(this.sessions);
      this._renderSessionList(this.sessions);
      this._populateSessionSelects(this.sessions);
    } catch (e) {
      Toast.show('Failed to load sessions: ' + e.message, 'error');
    }
  },

  _renderDashboardStats(sessions) {
    const counts = { running: 0, completed: 0, failed: 0 };
    sessions.forEach(s => { counts[s.status] = (counts[s.status] || 0) + 1; });
    document.getElementById('dash-total-sessions').textContent = sessions.length;
    document.getElementById('dash-running').textContent   = counts.running   || 0;
    document.getElementById('dash-completed').textContent = counts.completed || 0;
    document.getElementById('dash-failed').textContent    = counts.failed    || 0;
  },

  _renderSessionList(sessions) {
    const el = document.getElementById('session-list');
    if (!sessions.length) {
      el.innerHTML = '<div class="text-muted text-center py-4">No sessions yet. Start a new test!</div>';
      return;
    }
    el.innerHTML = sessions.map(s => `
      <div class="session-item" onclick="App.openSession(${s.id})">
        <div>
          <span class="status-badge status-${s.status}">${s.status}</span>
        </div>
        <div class="flex-grow-1">
          <div class="fw-semibold">${_esc(s.name)}</div>
          <div class="text-muted small">${_esc(s.drive_model || s.drive_device || '—')} &bull;
            ${s.n_jobs} job${s.n_jobs !== 1 ? 's' : ''} &bull;
            ${_relTime(s.created_at)}</div>
          ${s.tags ? `<div class="mt-1">${s.tags.split(',').map(t => `<span class="badge bg-surface text-muted me-1">${_esc(t.trim())}</span>`).join('')}</div>` : ''}
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-sm btn-outline-accent" onclick="event.stopPropagation();Results.openSession(${s.id})">
            <i class="bi bi-bar-chart-line"></i>
          </button>
          <button class="btn btn-sm btn-outline-secondary" onclick="event.stopPropagation();App.exportSession(${s.id})">
            <i class="bi bi-download"></i>
          </button>
        </div>
      </div>
    `).join('');
  },

  _populateSessionSelects(sessions) {
    const selects = [
      'results-session-select', 'logs-session-select',
      'cmp-session-select', 'chart-session-select',
      'ml-session-select',
    ];
    selects.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const isMulti = el.multiple;
      const prev = isMulti ? [] : el.value;
      // Keep placeholder option
      const opts = isMulti ? '' : '<option value="">— Select a session —</option>';
      el.innerHTML = opts + sessions.map(s =>
        `<option value="${s.id}">${_esc(s.name)} (${s.status})</option>`
      ).join('');
      if (!isMulti && prev) el.value = prev;
    });
  },

  openSession(id) {
    // Switch to results tab and load
    document.querySelector('[href="#tab-results"]').click();
    const sel = document.getElementById('results-session-select');
    sel.value = id;
    Results.load();
  },

  async exportSession(id) {
    window.open(API.getUrl(`/api/sessions/${id}/export`), '_blank');
  },
};


// ── Utility functions ────────────────────────────────────────────────────── //

function _esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _relTime(isoStr) {
  if (!isoStr) return '?';
  const diff = Date.now() - new Date(isoStr).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}

function _fmt(val, decimals = 0, suffix = '') {
  if (val === null || val === undefined || val === '') return '—';
  const n = parseFloat(val);
  if (isNaN(n)) return '—';
  return n.toFixed(decimals) + suffix;
}

// Start app when DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());
