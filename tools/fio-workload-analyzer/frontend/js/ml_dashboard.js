/* ── ML Insights dashboard ───────────────────────────────────────────────── */
'use strict';

const MLDash = {
  init() {
    // session selects populated by App
  },

  async train() {
    const models = [];
    if (document.getElementById('ml-train-anomaly').checked) models.push('anomaly');
    if (document.getElementById('ml-train-age').checked)     models.push('age');
    if (document.getElementById('ml-train-fw').checked)      models.push('fw');
    if (document.getElementById('ml-train-trend').checked)   models.push('trend');

    const el = document.getElementById('ml-train-result');
    el.innerHTML = '<div class="text-muted small">Training…</div>';

    try {
      const data = await API.post('/api/ml/train', { model_types: models });
      el.innerHTML = `<div class="text-green small mt-1">
        <i class="bi bi-check-circle me-1"></i>Trained on ${data.n_samples} samples
        ${Object.entries(data.trained || {}).map(([k, v]) =>
          `<div class="mt-1"><strong>${k}:</strong> ${JSON.stringify(v)}</div>`
        ).join('')}
      </div>`;
      Toast.show('ML models trained successfully', 'success');
    } catch (e) {
      el.innerHTML = `<div class="text-red small mt-1">${e.message}</div>`;
      Toast.show('Training failed: ' + e.message, 'error');
    }
  },

  async predict() {
    const sid = document.getElementById('ml-session-select').value;
    if (!sid) { Toast.show('Select a session first', 'warn'); return; }

    const panel = document.getElementById('ml-results-panel');
    panel.innerHTML = '<div class="text-center text-muted py-4">Running inference…</div>';

    try {
      const data = await API.get(`/api/ml/predict/${sid}`);
      this._renderPredictions(data.predictions || []);
    } catch (e) {
      panel.innerHTML = `<div class="text-red">${e.message}</div>`;
      Toast.show('Inference failed: ' + e.message, 'error');
    }
  },

  _renderPredictions(predictions) {
    const panel = document.getElementById('ml-results-panel');
    if (!predictions.length) {
      panel.innerHTML = '<div class="text-muted">No predictions returned.</div>';
      return;
    }

    panel.innerHTML = predictions.map(p => this._renderJobPrediction(p)).join('');
  },

  _renderJobPrediction(p) {
    const health  = p.health  || {};
    const anomaly = p.anomaly || {};
    const age     = p.age     || {};
    const fw      = p.fw      || {};
    const trend   = p.trend   || [];

    const grade = health.grade || '?';
    const score = health.health_score ?? '—';
    const reasons = (health.reasons || []).map(r => `<li>${_esc(r)}</li>`).join('');

    const fwLabel  = fw.fw_label  || '—';
    const fwConf   = fw.confidence !== undefined ? `${(fw.confidence*100).toFixed(0)}%` : '—';
    const ageWear  = age.estimated_wear_pct ?? '—';
    const ageInterp = age.interpretation || '';
    const isAnom   = anomaly.is_anomaly;
    const anomScore = anomaly.anomaly_score ?? '—';

    const trendRows = trend.filter(t => !t.error).map(t =>
      `<tr>
        <td>${_fmt(t.tbw_gb, 1)} TB</td>
        <td>${_fmt(t.predicted_iops, 0)}</td>
        <td>${t.extrapolated ? '<span class="text-yellow">Extrapolated</span>' : '<span class="text-green">Interpolated</span>'}</td>
      </tr>`
    ).join('');

    return `
    <div class="ml-result-card">
      <div class="d-flex justify-content-between align-items-start mb-3">
        <div>
          <h6 class="mb-0 text-accent">${_esc(p.job_name)}</h6>
          <div class="text-muted small">Job #${p.job_id}</div>
        </div>
        <div class="health-gauge grade-${grade}" title="Health Score: ${score}/100">${grade}</div>
      </div>

      <div class="row g-3">

        <!-- Health -->
        <div class="col-md-6">
          <div class="p-2 rounded" style="background:#181825;border:1px solid #313244">
            <div class="text-muted small mb-1 text-uppercase" style="letter-spacing:.06em">Drive Health</div>
            <div class="d-flex align-items-center gap-2 mb-1">
              <div class="progress flex-grow-1" style="height:8px">
                <div class="progress-bar ${_healthBarColor(score)}" style="width:${score}%"></div>
              </div>
              <span class="fw-bold">${score}%</span>
            </div>
            ${reasons ? `<ul class="mb-0 ps-3 text-muted" style="font-size:.78rem">${reasons}</ul>` : ''}
          </div>
        </div>

        <!-- Anomaly -->
        <div class="col-md-6">
          <div class="p-2 rounded" style="background:#181825;border:1px solid #313244">
            <div class="text-muted small mb-1 text-uppercase" style="letter-spacing:.06em">Anomaly Detection</div>
            <div class="${isAnom ? 'text-red' : 'text-green'} fw-semibold">
              <i class="bi bi-${isAnom ? 'exclamation-triangle-fill' : 'check-circle-fill'} me-1"></i>
              ${isAnom ? 'Anomalous Performance' : 'Normal Performance'}
            </div>
            <div class="text-muted small mt-1">Isolation score: ${anomScore}</div>
          </div>
        </div>

        <!-- Drive Age -->
        <div class="col-md-6">
          <div class="p-2 rounded" style="background:#181825;border:1px solid #313244">
            <div class="text-muted small mb-1 text-uppercase" style="letter-spacing:.06em">NAND Age Estimation</div>
            <div class="d-flex align-items-center gap-2">
              <div class="progress flex-grow-1" style="height:8px">
                <div class="progress-bar ${_wearBarColor(ageWear)}" style="width:${ageWear}%"></div>
              </div>
              <span class="fw-bold">${ageWear}%</span>
            </div>
            <div class="text-muted small mt-1">${_esc(ageInterp)}</div>
          </div>
        </div>

        <!-- FW Fingerprint -->
        <div class="col-md-6">
          <div class="p-2 rounded" style="background:#181825;border:1px solid #313244">
            <div class="text-muted small mb-1 text-uppercase" style="letter-spacing:.06em">FW Algorithm Fingerprint</div>
            <div class="fw-semibold text-mauve">${_esc(fwLabel)}</div>
            <div class="text-muted small mt-1">Confidence: ${fwConf}
              &bull; Cluster ${fw.cluster_id ?? '—'}</div>
          </div>
        </div>

        <!-- Trend -->
        ${trendRows ? `
        <div class="col-12">
          <div class="p-2 rounded" style="background:#181825;border:1px solid #313244">
            <div class="text-muted small mb-1 text-uppercase" style="letter-spacing:.06em">Performance Trend Forecast</div>
            <div class="table-responsive">
              <table class="table table-dark table-sm mb-0" style="font-size:.78rem">
                <thead><tr><th>TBW</th><th>Predicted IOPS</th><th>Type</th></tr></thead>
                <tbody>${trendRows}</tbody>
              </table>
            </div>
          </div>
        </div>` : ''}

      </div>
    </div>`;
  },
};


function _healthBarColor(score) {
  if (score >= 75) return 'bg-success';
  if (score >= 50) return 'bg-warning';
  return 'bg-danger';
}

function _wearBarColor(wear) {
  if (wear < 30) return 'bg-success';
  if (wear < 70) return 'bg-warning';
  return 'bg-danger';
}


// ── Log Viewer ───────────────────────────────────────────────────────────── //

const LogViewer = {
  _currentLogId: null,

  init() {},

  async load() {
    const sid    = document.getElementById('logs-session-select').value;
    const phase  = document.getElementById('logs-phase-filter').value;
    const ltype  = document.getElementById('logs-type-filter').value;
    if (!sid) return;

    try {
      let url = `/api/sessions/${sid}/logs`;
      const params = [];
      if (phase) params.push(`phase=${phase}`);
      if (ltype) params.push(`log_type=${ltype}`);
      if (params.length) url += '?' + params.join('&');

      const data = await API.get(url);
      this._renderLogList(data.logs || []);
    } catch (e) {
      Toast.show('Failed to load logs: ' + e.message, 'error');
    }
  },

  _renderLogList(logs) {
    const el = document.getElementById('log-list');
    if (!logs.length) {
      el.innerHTML = '<div class="text-muted small text-center py-4">No logs captured</div>';
      return;
    }
    el.innerHTML = logs.map(l => `
      <div class="log-file-item ${l.id === this._currentLogId ? 'active' : ''}"
           onclick="LogViewer.viewLog(${l.id}, this)">
        <div class="d-flex justify-content-between">
          <span class="fw-semibold text-accent small">${_esc(l.log_type)}</span>
          <span class="badge ${l.phase === 'pre' ? 'bg-surface text-muted' : 'bg-dark text-accent'}">${l.phase}</span>
        </div>
        <div class="text-muted" style="font-size:.72rem">${l.captured_at ? new Date(l.captured_at).toLocaleString() : ''}</div>
        <div class="text-muted" style="font-size:.72rem">${_fmt(l.size / 1024, 1, ' KB')}</div>
      </div>
    `).join('');
  },

  async viewLog(id, el) {
    this._currentLogId = id;
    document.querySelectorAll('.log-file-item').forEach(e => e.classList.remove('active'));
    el.classList.add('active');

    try {
      const data = await API.get(`/api/logs/${id}/content`);
      document.getElementById('log-content-view').textContent = data.content;
      document.getElementById('log-viewer-title').textContent = `Log #${id}`;
    } catch (e) {
      Toast.show('Failed to load log content: ' + e.message, 'error');
    }
  },

  copyContent() {
    const text = document.getElementById('log-content-view').textContent;
    navigator.clipboard.writeText(text).then(() => Toast.show('Copied!', 'success'));
  },
};
