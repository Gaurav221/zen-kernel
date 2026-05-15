/* ── Chart rendering (Chart.js) ──────────────────────────────────────────── */
'use strict';

const PALETTE = {
  blue:   '#89b4fa',
  green:  '#a6e3a1',
  red:    '#f38ba8',
  yellow: '#f9e2af',
  mauve:  '#cba6f7',
  teal:   '#94e2d5',
  peach:  '#fab387',
  sky:    '#89dceb',
};

const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      labels: { color: '#cdd6f4', font: { size: 11 } },
    },
    tooltip: {
      backgroundColor: '#1e1e2e',
      titleColor: '#cdd6f4',
      bodyColor: '#a6adc8',
      borderColor: '#313244',
      borderWidth: 1,
    },
  },
  scales: {
    x: {
      ticks: { color: '#7f849c' },
      grid:  { color: '#313244' },
    },
    y: {
      ticks: { color: '#7f849c' },
      grid:  { color: '#313244' },
    },
  },
};

function _applyDefaults(config) {
  config.options = _deepMerge(JSON.parse(JSON.stringify(CHART_DEFAULTS)), config.options || {});
  return config;
}

function _deepMerge(target, src) {
  for (const k of Object.keys(src)) {
    if (src[k] && typeof src[k] === 'object' && !Array.isArray(src[k])) {
      target[k] = target[k] || {};
      _deepMerge(target[k], src[k]);
    } else {
      target[k] = src[k];
    }
  }
  return target;
}

const _chartInstances = {};

function _getOrCreate(canvasId, config) {
  if (_chartInstances[canvasId]) {
    _chartInstances[canvasId].destroy();
  }
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;
  _chartInstances[canvasId] = new Chart(canvas, _applyDefaults(config));
  return _chartInstances[canvasId];
}

// ── Results tab charts ────────────────────────────────────────────────────

const Charts = {
  renderResultsCharts(results) {
    if (!results.length) {
      document.getElementById('results-charts-row').innerHTML = '';
      return;
    }

    const container = document.getElementById('results-charts-row');
    container.innerHTML = `
      <div class="col-md-6">
        <div class="card-panel">
          <h6 class="mb-2">IOPS per Job</h6>
          <div style="height:240px"><canvas id="res-iops-chart"></canvas></div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="card-panel">
          <h6 class="mb-2">Bandwidth per Job (MB/s)</h6>
          <div style="height:240px"><canvas id="res-bw-chart"></canvas></div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="card-panel mt-0">
          <h6 class="mb-2">Latency Percentiles — Read (µs, log scale)</h6>
          <div style="height:240px"><canvas id="res-rlat-chart"></canvas></div>
        </div>
      </div>
      <div class="col-md-6">
        <div class="card-panel mt-0">
          <h6 class="mb-2">Latency Percentiles — Write (µs, log scale)</h6>
          <div style="height:240px"><canvas id="res-wlat-chart"></canvas></div>
        </div>
      </div>
    `;

    const labels = results.map(r => r.job.job_name);
    const m = results.map(r => r.metrics);

    // IOPS chart
    _getOrCreate('res-iops-chart', {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'Read IOPS',  data: m.map(x => x.read_iops  || 0), backgroundColor: PALETTE.blue  + 'cc' },
          { label: 'Write IOPS', data: m.map(x => x.write_iops || 0), backgroundColor: PALETTE.green + 'cc' },
        ],
      },
      options: { scales: { y: { title: { display: true, text: 'IOPS', color: '#7f849c' } } } },
    });

    // BW chart
    _getOrCreate('res-bw-chart', {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'Read BW',  data: m.map(x => x.read_bw_mbps  || 0), backgroundColor: PALETTE.teal  + 'cc' },
          { label: 'Write BW', data: m.map(x => x.write_bw_mbps || 0), backgroundColor: PALETTE.mauve + 'cc' },
        ],
      },
    });

    // Read latency percentiles
    const pctLabels = ['P50', 'P90', 'P95', 'P99', 'P99.9'];
    const pctFields = ['read_p50_us', 'read_p99_us', 'read_p999_us'];
    const colors = Object.values(PALETTE);

    _getOrCreate('res-rlat-chart', {
      type: 'bar',
      data: {
        labels: pctLabels.slice(0, 5),
        datasets: results.map((r, i) => ({
          label: r.job.job_name,
          data: [
            r.metrics.read_p50_us  || 0,
            (r.job.result?.read_clat_p90_ns  || 0) / 1000,
            (r.job.result?.read_clat_p95_ns  || 0) / 1000,
            r.metrics.read_p99_us  || 0,
            r.metrics.read_p999_us || 0,
          ],
          backgroundColor: colors[i % colors.length] + 'aa',
        })),
      },
      options: { scales: { y: { type: 'logarithmic', title: { display: true, text: 'µs', color: '#7f849c' } } } },
    });

    // Write latency percentiles
    _getOrCreate('res-wlat-chart', {
      type: 'bar',
      data: {
        labels: pctLabels.slice(0, 5),
        datasets: results.map((r, i) => ({
          label: r.job.job_name,
          data: [
            r.metrics.write_p50_us  || 0,
            (r.job.result?.write_clat_p90_ns || 0) / 1000,
            (r.job.result?.write_clat_p95_ns || 0) / 1000,
            r.metrics.write_p99_us  || 0,
            r.metrics.write_p999_us || 0,
          ],
          backgroundColor: colors[i % colors.length] + 'aa',
        })),
      },
      options: { scales: { y: { type: 'logarithmic', title: { display: true, text: 'µs', color: '#7f849c' } } } },
    });
  },
};


// ── Analysis tab charts ────────────────────────────────────────────────────

const Analysis = {
  _tsChart1: null,
  _tsChart2: null,
  _mainChart: null,
  _allResults: [],

  async init() {
    await this._fetchAllResults();
    this._populateJobSelect();
  },

  async _fetchAllResults() {
    try {
      const sessions = App.sessions;
      this._allResults = [];
      for (const s of sessions.slice(0, 20)) {  // limit
        try {
          const data = await API.get(`/api/sessions/${s.id}/results`);
          data.results.forEach(r => {
            r._session = s;
            this._allResults.push(r);
          });
        } catch { /* skip */ }
      }
    } catch { /* ignore */ }
  },

  _populateJobSelect() {
    const sel = document.getElementById('ts-job-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">— Select a job —</option>';
    this._allResults.forEach(r => {
      const opt = document.createElement('option');
      opt.value   = r.job.id;
      opt.textContent = `[${r._session?.name}] ${r.job.job_name} (${r.job.rw} bs=${r.job.bs} qd=${r.job.iodepth})`;
      sel.appendChild(opt);
    });
  },

  async loadTimeSeries() {
    const jobId = document.getElementById('ts-job-select').value;
    if (!jobId) return;
    try {
      const data = await API.get(`/api/jobs/${jobId}/timeseries`);
      this._renderTSCharts(data.data || []);
      this._renderTSStats(data.stats || {});
      this._renderCliffDetection(data.stats || {});
    } catch (e) {
      Toast.show('Failed to load time-series: ' + e.message, 'error');
    }
  },

  _renderTSCharts(rows) {
    const t  = rows.map(r => r.t.toFixed(1));
    const ri = rows.map(r => r.iops_read);
    const wi = rows.map(r => r.iops_write);
    const rl = rows.map(r => r.lat_read_us);
    const wl = rows.map(r => r.lat_write_us);

    _getOrCreate('ts-chart-iops', {
      type: 'line',
      data: {
        labels: t,
        datasets: [
          { label: 'Read IOPS',  data: ri, borderColor: PALETTE.blue,  borderWidth: 1.5, pointRadius: 0, fill: false },
          { label: 'Write IOPS', data: wi, borderColor: PALETTE.green, borderWidth: 1.5, pointRadius: 0, fill: false },
        ],
      },
      options: {
        plugins: { legend: { labels: { color: '#cdd6f4', font: { size: 10 } } } },
        scales: {
          x: { ticks: { color: '#7f849c', maxTicksLimit: 10 }, grid: { color: '#313244' } },
          y: { ticks: { color: '#7f849c' }, grid: { color: '#313244' }, title: { display: true, text: 'IOPS', color: '#7f849c' } },
        },
      },
    });

    _getOrCreate('ts-chart-lat', {
      type: 'line',
      data: {
        labels: t,
        datasets: [
          { label: 'R Lat (µs)', data: rl, borderColor: PALETTE.teal,  borderWidth: 1.5, pointRadius: 0, fill: false },
          { label: 'W Lat (µs)', data: wl, borderColor: PALETTE.mauve, borderWidth: 1.5, pointRadius: 0, fill: false },
        ],
      },
      options: {
        plugins: { legend: { labels: { color: '#cdd6f4', font: { size: 10 } } } },
        scales: {
          x: { ticks: { color: '#7f849c', maxTicksLimit: 10 }, grid: { color: '#313244' } },
          y: { ticks: { color: '#7f849c' }, grid: { color: '#313244' }, title: { display: true, text: 'µs', color: '#7f849c' } },
        },
      },
    });
  },

  _renderTSStats(stats) {
    const el = document.getElementById('ts-stats-panel');
    if (!Object.keys(stats).length) { el.innerHTML = ''; return; }
    const rows = [
      ['Read IOPS Mean',   _fmt(stats.read_iops_mean,  0)],
      ['Read IOPS CV',     _fmt(stats.read_iops_cv,    3)],
      ['Write IOPS Mean',  _fmt(stats.write_iops_mean, 0)],
      ['Write IOPS CV',    _fmt(stats.write_iops_cv,   3)],
      ['Read Lat Mean',    _fmt(stats.read_lat_us_mean,  1, ' µs')],
      ['Write Lat Mean',   _fmt(stats.write_lat_us_mean, 1, ' µs')],
      ['R Lat Spikes',     stats.read_lat_spikes  ?? '—'],
      ['W Lat Spikes',     stats.write_lat_spikes ?? '—'],
    ];
    el.innerHTML = `<div class="mt-2">
      <table class="table table-dark table-sm mb-0" style="font-size:0.78rem">
        ${rows.map(([k,v]) => `<tr><td class="text-muted">${k}</td><td class="text-end">${v}</td></tr>`).join('')}
      </table>
    </div>`;
  },

  _renderCliffDetection(stats) {
    const el = document.getElementById('cliff-results');
    const n = stats.read_lat_spikes ?? stats.write_lat_spikes;
    if (n === undefined) { el.textContent = 'No time-series data.'; return; }
    const rateR = _fmt(stats.read_spike_rate,  3);
    const rateW = _fmt(stats.write_spike_rate, 3);
    el.innerHTML = `
      <div>R Lat spikes (3σ): <span class="text-yellow">${stats.read_lat_spikes ?? '—'}</span></div>
      <div>W Lat spikes (3σ): <span class="text-yellow">${stats.write_lat_spikes ?? '—'}</span></div>
      <div class="mt-1">R spike rate: <span class="text-accent">${rateR}</span></div>
      <div>W spike rate: <span class="text-accent">${rateW}</span></div>
      <div class="mt-2 text-muted">High spike rate (>0.05) suggests GC pauses or thermal throttling.</div>
    `;
  },

  async compare() {
    const sel = document.getElementById('cmp-session-select');
    const ids = Array.from(sel.selectedOptions).map(o => o.value).join(',');
    if (!ids) { Toast.show('Select sessions to compare', 'warn'); return; }
    try {
      const data = await API.get(`/api/sessions/compare?ids=${ids}`);
      this._renderComparisonTable(data.table || []);
    } catch (e) {
      Toast.show('Comparison failed: ' + e.message, 'error');
    }
  },

  _renderComparisonTable(rows) {
    const el = document.getElementById('comparison-table');
    if (!rows.length) { el.innerHTML = '<div class="text-muted">No data</div>'; return; }
    const cols = Object.keys(rows[0]);
    el.innerHTML = `<div class="table-responsive mt-2">
      <table class="table table-dark table-sm table-hover">
        <thead><tr>${cols.map(c => `<th>${_esc(c)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r =>
          `<tr>${cols.map(c => `<td>${r[c] ?? '—'}</td>`).join('')}</tr>`
        ).join('')}</tbody>
      </table>
    </div>`;
  },

  async renderChart() {
    const xAxis = document.getElementById('chart-x-axis').value;
    const yAxis = document.getElementById('chart-y-axis').value;
    const sidFilter = document.getElementById('chart-session-select').value;

    let data = this._allResults;
    if (sidFilter) data = data.filter(r => String(r._session?.id) === sidFilter);
    if (!data.length) { Toast.show('No data to plot', 'warn'); return; }

    const xVals = data.map(r => {
      if (xAxis === 'iodepth') return r.job.iodepth;
      if (xAxis === 'bs') return r.job.bs;
      if (xAxis === 'runtime_s') return r.job.runtime_s;
      return r.job[xAxis];
    });
    const yVals = data.map(r => r.metrics[yAxis] ?? r.job.result?.[yAxis] ?? 0);

    _getOrCreate('analysis-chart', {
      type: 'scatter',
      data: {
        datasets: [{
          label: yAxis,
          data: xVals.map((x, i) => ({ x: isNaN(x) ? i : x, y: yVals[i] })),
          backgroundColor: PALETTE.blue + 'bb',
          borderColor: PALETTE.blue,
          pointRadius: 5,
        }],
      },
      options: {
        plugins: { tooltip: {
          callbacks: {
            label: ctx => {
              const r = data[ctx.dataIndex];
              return `${r.job.job_name}: x=${ctx.parsed.x} y=${ctx.parsed.y.toFixed(1)}`;
            },
          },
        }},
        scales: {
          x: { title: { display: true, text: xAxis, color: '#7f849c' }, ticks: { color: '#7f849c' }, grid: { color: '#313244' } },
          y: { title: { display: true, text: yAxis, color: '#7f849c' }, ticks: { color: '#7f849c' }, grid: { color: '#313244' } },
        },
      },
    });
  },
};
