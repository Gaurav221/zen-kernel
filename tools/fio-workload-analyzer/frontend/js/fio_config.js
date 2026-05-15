/* ── FIO Configuration & test submission ─────────────────────────────────── */
'use strict';

const FioConfig = {
  profiles: {},
  selectedProfile: null,
  _ws: null,
  _sessionId: null,
  _startTime: null,
  _progressTimer: null,

  async init() {
    await this._loadProfiles();
    this.addJobRow();
  },

  async _loadProfiles() {
    try {
      const data = await API.get('/api/profiles');
      this.profiles = data;
      this._renderProfileButtons();
    } catch (e) {
      console.error('profiles:', e);
    }
  },

  _renderProfileButtons() {
    const container = document.getElementById('profile-buttons');
    const custom = { label: 'Custom', n_jobs: 0 };

    const allProfiles = { custom, ...this.profiles };
    container.innerHTML = Object.entries(allProfiles).map(([key, p]) =>
      `<button class="profile-btn ${key === 'custom' ? 'active' : ''}"
               data-key="${key}"
               onclick="FioConfig.selectProfile('${key}')">${_esc(p.label)}${p.n_jobs ? ` <span class="text-muted">(${p.n_jobs})</span>` : ''}</button>`
    ).join('');
    this.selectedProfile = 'custom';
    document.getElementById('custom-job-panel').style.display = '';
  },

  selectProfile(key) {
    this.selectedProfile = key;
    document.querySelectorAll('.profile-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.key === key);
    });
    document.getElementById('custom-job-panel').style.display = key === 'custom' ? '' : 'none';
  },

  addJobRow() {
    const tmpl = document.getElementById('job-row-template');
    const clone = tmpl.content.cloneNode(true);
    document.getElementById('job-rows').appendChild(clone);
  },

  removeJobRow(btn) {
    btn.closest('.job-row').remove();
  },

  async discoverDrives() {
    try {
      const data = await API.get('/api/drives');
      this._renderDriveList(data.drives || []);
    } catch (e) {
      Toast.show('Drive discovery failed: ' + e.message, 'error');
    }
  },

  _renderDriveList(drives) {
    const el = document.getElementById('drive-list');
    if (!drives.length) {
      el.innerHTML = '<div class="text-muted small">No drives discovered.</div>';
      return;
    }
    el.innerHTML = drives.map(d =>
      `<button class="btn btn-sm btn-outline-secondary me-1 mb-1" onclick="FioConfig.selectDrive('${d.device}')">
        <i class="bi bi-device-hdd me-1"></i>${_esc(d.device)}
        <span class="text-muted ms-1">${_esc(d.model || '')} ${_esc(d.size || d.capacity_gb ? d.capacity_gb+'GB' : '')}</span>
      </button>`
    ).join('');
  },

  selectDrive(device) {
    document.getElementById('cfg-device').value = device;
  },

  _buildJobSpecs() {
    if (this.selectedProfile !== 'custom') return null;  // backend will use profile

    const rows = document.querySelectorAll('#job-rows .job-row');
    const device = document.getElementById('cfg-device').value.trim();
    const runtime = parseInt(document.getElementById('cfg-runtime').value) || 60;
    const ramp    = parseInt(document.getElementById('cfg-ramp').value) || 10;
    const engine  = document.getElementById('cfg-ioengine').value;
    const size    = document.getElementById('cfg-size').value || '100%';
    const direct  = document.getElementById('cfg-direct').checked;

    return Array.from(rows).map((row, i) => ({
      rw:          row.querySelector('.rw-select').value,
      bs:          row.querySelector('.bs-select').value,
      iodepth:     parseInt(row.querySelector('.qd-select').value),
      numjobs:     parseInt(row.querySelector('.numjobs-input').value) || 1,
      rwmixread:   parseInt(row.querySelector('.rwmix-input').value) || 70,
      job_name:    row.querySelector('.jobname-input').value || `job_${i+1}`,
      filename:    device,
      runtime_s:   runtime,
      ramp_time_s: ramp,
      ioengine:    engine,
      size:        size,
      direct:      direct,
      group_reporting: document.getElementById('cfg-group-reporting').checked,
    }));
  },

  async submit() {
    const name = document.getElementById('cfg-name').value.trim();
    if (!name) { Toast.show('Please enter a session name', 'warn'); return; }

    const device = document.getElementById('cfg-device').value.trim();
    if (!device) { Toast.show('Please specify a target device or file', 'warn'); return; }

    const isCustom = this.selectedProfile === 'custom';
    const jobSpecs = isCustom ? this._buildJobSpecs() : [{filename: device, runtime_s: parseInt(document.getElementById('cfg-runtime').value)||60}];

    if (isCustom && !jobSpecs.length) {
      Toast.show('Add at least one job', 'warn'); return;
    }

    const payload = {
      name,
      description:  document.getElementById('cfg-description').value,
      tags:         document.getElementById('cfg-tags').value,
      jobs:         jobSpecs,
      profile:      isCustom ? null : this.selectedProfile,
      capture_logs: document.getElementById('cfg-capture-logs').checked,
      drive_device: device,
    };

    try {
      const resp = await API.post('/api/sessions', payload);
      this._sessionId = resp.session_id;
      Toast.show(`Session #${resp.session_id} started`, 'success');
      this._startLiveOutput(resp.session_id);
      await App.loadDashboard();
    } catch (e) {
      Toast.show('Failed to start test: ' + e.message, 'error');
    }
  },

  _startLiveOutput(sessionId) {
    const outputEl  = document.getElementById('live-output');
    const statusEl  = document.getElementById('live-status');
    const progressEl = document.getElementById('live-progress');
    const progressBar = document.getElementById('live-progress-bar');
    const jobLabel   = document.getElementById('live-job-label');
    const elapsedEl  = document.getElementById('live-elapsed');

    outputEl.textContent = '';
    statusEl.textContent = 'Running';
    statusEl.className   = 'badge bg-accent text-dark';
    progressEl.style.display = '';
    this._startTime = Date.now();
    let pct = 0;

    this._progressTimer = setInterval(() => {
      const elapsed = Math.floor((Date.now() - this._startTime) / 1000);
      elapsedEl.textContent = `${elapsed}s`;
      pct = Math.min(pct + 0.5, 90);
      progressBar.style.width = pct + '%';
    }, 500);

    const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl   = `${wsProto}://${location.host}/ws/sessions/${sessionId}`;
    this._ws = new WebSocket(wsUrl);

    this._ws.onmessage = evt => {
      const line = evt.data;
      // Colour-code terminal lines
      let cls = '';
      if (line.startsWith('[error]')) cls = 't-err';
      else if (line.startsWith('[result]')) cls = 't-ok';
      else if (line.startsWith('[job]')) cls = 't-info';
      else if (line.startsWith('[logs]')) cls = 't-warn';
      else if (line.startsWith('[session]')) cls = 't-info';

      if (line.startsWith('[job]')) {
        const m = line.match(/Starting (.+?)(?:\n|$)/);
        if (m) jobLabel.textContent = m[1];
      }

      const span = document.createElement('span');
      span.className = cls;
      span.textContent = line;
      outputEl.appendChild(span);
      outputEl.scrollTop = outputEl.scrollHeight;
    };

    this._ws.onclose = () => {
      clearInterval(this._progressTimer);
      progressBar.style.width = '100%';
      statusEl.textContent = 'Done';
      statusEl.className   = 'badge bg-success';
      setTimeout(() => { progressEl.style.display = 'none'; }, 2000);
      App.loadDashboard();
    };

    this._ws.onerror = () => {
      statusEl.textContent = 'Error';
      statusEl.className   = 'badge bg-danger';
    };
  },

  clearOutput() {
    document.getElementById('live-output').textContent = '';
  },

  reset() {
    document.getElementById('cfg-name').value = '';
    document.getElementById('cfg-description').value = '';
    document.getElementById('cfg-tags').value = '';
    document.getElementById('job-rows').innerHTML = '';
    this.addJobRow();
    this.selectProfile('custom');
  },
};
