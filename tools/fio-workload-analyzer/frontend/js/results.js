/* ── Results tab ─────────────────────────────────────────────────────────── */
'use strict';

const Results = {
  _currentSession: null,
  _charts: {},

  init() {
    // nothing to pre-init; populated by App._populateSessionSelects
  },

  openSession(id) {
    document.querySelector('[href="#tab-results"]').click();
    document.getElementById('results-session-select').value = id;
    this.load();
  },

  async load() {
    const sid = document.getElementById('results-session-select').value;
    if (!sid) return;

    try {
      const [detail, resultsData] = await Promise.all([
        API.get(`/api/sessions/${sid}`),
        API.get(`/api/sessions/${sid}/results`),
      ]);
      this._currentSession = detail;
      this._renderKPIs(resultsData.results);
      this._renderTable(resultsData.results);
      Charts.renderResultsCharts(resultsData.results);
    } catch (e) {
      Toast.show('Failed to load results: ' + e.message, 'error');
    }
  },

  _renderKPIs(results) {
    const el = document.getElementById('results-kpi-row');
    if (!results.length) { el.style.cssText = 'display:none!important'; return; }

    el.removeAttribute('style');

    // Aggregate across jobs
    let maxReadIOPS  = 0, maxWriteIOPS = 0;
    let maxReadBW    = 0, maxWriteBW   = 0;
    let minReadP99   = Infinity, minWriteP99 = Infinity;

    results.forEach(r => {
      const m = r.metrics;
      maxReadIOPS  = Math.max(maxReadIOPS,  m.read_iops  || 0);
      maxWriteIOPS = Math.max(maxWriteIOPS, m.write_iops || 0);
      maxReadBW    = Math.max(maxReadBW,    m.read_bw_mbps  || 0);
      maxWriteBW   = Math.max(maxWriteBW,   m.write_bw_mbps || 0);
      if (m.read_p99_us)  minReadP99  = Math.min(minReadP99,  m.read_p99_us);
      if (m.write_p99_us) minWriteP99 = Math.min(minWriteP99, m.write_p99_us);
    });

    const kpis = [
      { label: 'Peak Read IOPS',  value: _fmt(maxReadIOPS, 0),   color: 'text-accent'  },
      { label: 'Peak Write IOPS', value: _fmt(maxWriteIOPS, 0),  color: 'text-green'   },
      { label: 'Peak Read BW',    value: _fmt(maxReadBW, 1, ' MB/s'),  color: 'text-accent' },
      { label: 'Peak Write BW',   value: _fmt(maxWriteBW, 1, ' MB/s'), color: 'text-green'  },
      { label: 'Best Read P99',   value: _fmt(minReadP99  === Infinity ? null : minReadP99,  1, ' µs'), color: 'text-teal'   },
      { label: 'Best Write P99',  value: _fmt(minWriteP99 === Infinity ? null : minWriteP99, 1, ' µs'), color: 'text-mauve'  },
    ];

    el.innerHTML = kpis.map(k => `
      <div class="col-md-2 col-6">
        <div class="kpi-card">
          <div class="kpi-label">${k.label}</div>
          <div class="kpi-value ${k.color}">${k.value}</div>
        </div>
      </div>
    `).join('');
  },

  _renderTable(results) {
    const thead = document.getElementById('results-thead');
    const tbody = document.getElementById('results-tbody');

    if (!results.length) {
      thead.innerHTML = ''; tbody.innerHTML = '<tr><td colspan="20" class="text-center text-muted">No results yet</td></tr>';
      return;
    }

    thead.innerHTML = `<tr>
      <th>Job</th><th>Pattern</th><th>BS</th><th>QD</th>
      <th>R IOPS</th><th>W IOPS</th>
      <th>R BW (MB/s)</th><th>W BW (MB/s)</th>
      <th>R P50 (µs)</th><th>R P99 (µs)</th><th>R P99.9 (µs)</th>
      <th>W P50 (µs)</th><th>W P99 (µs)</th><th>W P99.9 (µs)</th>
      <th>CPU %</th><th>GC Score</th><th>WA Est.</th>
    </tr>`;

    tbody.innerHTML = results.map(r => {
      const j = r.job;
      const m = r.metrics;
      const res = j.result;
      return `<tr>
        <td class="text-accent fw-semibold">${_esc(j.job_name)}</td>
        <td>${_esc(j.rw)}</td>
        <td>${_esc(j.bs)}</td>
        <td>${j.iodepth}</td>
        <td>${_fmt(m.read_iops, 0)}</td>
        <td>${_fmt(m.write_iops, 0)}</td>
        <td>${_fmt(m.read_bw_mbps, 1)}</td>
        <td>${_fmt(m.write_bw_mbps, 1)}</td>
        <td>${_fmt(m.read_p50_us, 1)}</td>
        <td>${_colorLat(_fmt(m.read_p99_us, 1), m.read_p99_us)}</td>
        <td>${_fmt(m.read_p999_us, 1)}</td>
        <td>${_fmt(m.write_p50_us, 1)}</td>
        <td>${_colorLat(_fmt(m.write_p99_us, 1), m.write_p99_us)}</td>
        <td>${_fmt(m.write_p999_us, 1)}</td>
        <td>${_fmt((m.cpu_usr||0) + (m.cpu_sys||0), 1)}</td>
        <td>${_gcBar(m.gc_pause_score)}</td>
        <td>${_fmt(m.write_amp_est, 2)}</td>
      </tr>`;
    }).join('');
  },

  async generatePlots() {
    const sid = document.getElementById('results-session-select').value;
    if (!sid) { Toast.show('Select a session first', 'warn'); return; }
    try {
      Toast.show('Generating plots…', 'info');
      const data = await API.post(`/api/sessions/${sid}/plots`, {});
      this._renderPlotGallery(data.plots || {});
    } catch (e) {
      Toast.show('Plot generation failed: ' + e.message, 'error');
    }
  },

  _renderPlotGallery(plots) {
    const el = document.getElementById('plot-gallery');
    const entries = Object.entries(plots);
    if (!entries.length) { el.innerHTML = ''; return; }

    el.innerHTML = `
      <h6 class="mb-3 mt-2">Plot Gallery</h6>
      <div class="row g-3">
        ${entries.map(([name, path]) => {
          const filename = path.split('/').pop();
          return `
            <div class="col-md-4">
              <div class="plot-thumb" onclick="window.open('${API.getUrl('/api/plots/'+filename)}','_blank')">
                <img src="${API.getUrl('/api/plots/'+filename)}" alt="${_esc(name)}"
                     onerror="this.src='data:image/svg+xml,<svg/>'">
                <div class="text-muted small text-center py-1">${_esc(name)}</div>
              </div>
            </div>`;
        }).join('')}
      </div>`;
  },

  downloadExcel() {
    const sid = document.getElementById('results-session-select').value;
    if (!sid) { Toast.show('Select a session first', 'warn'); return; }
    window.open(API.getUrl(`/api/sessions/${sid}/export`), '_blank');
  },
};


// ── Helpers ────────────────────────────────────────────────────────────────

function _colorLat(displayStr, val) {
  if (val === null || val === undefined) return '—';
  if (val < 100)  return `<span class="text-green">${displayStr}</span>`;
  if (val < 500)  return `<span class="text-accent">${displayStr}</span>`;
  if (val < 2000) return `<span class="text-yellow">${displayStr}</span>`;
  return `<span class="text-red">${displayStr}</span>`;
}

function _gcBar(score) {
  if (score === null || score === undefined) return '—';
  const pct = Math.round(score * 100);
  const color = pct < 20 ? 'bg-success' : pct < 60 ? 'bg-warning' : 'bg-danger';
  return `<div class="progress" style="height:8px;width:60px;background:#313244">
    <div class="progress-bar ${color}" style="width:${pct}%" title="${score}"></div>
  </div>`;
}
