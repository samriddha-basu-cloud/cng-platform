// ================= shared helpers =================
function chartsAvailable() {
  if (typeof Chart === "undefined") {
    toast("Charts failed to load (blocked by browser/network) — numbers are still shown in the tables above.", "error");
    return false;
  }
  return true;
}
function fmtNum(v, digits = 1) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}
function fmtPct(v) {
  if (v === null || v === undefined) return "—";
  return (v * 100).toFixed(1) + "%";
}
function statusBadge(status) {
  const cls = status === "optimal" ? "ok" : (status === "infeasible" ? "critical" : "warn");
  return `<span class="badge ${cls}">${status}</span>`;
}
function diagnosticsHTML(diag) {
  if (!diag || !diag.findings) return "";
  return `<div style="margin-top:10px;">
    <div class="text-secondary" style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Why infeasible</div>
    ${diag.findings.map(f => `
      <div style="padding:8px 0;border-bottom:1px solid var(--border-soft);">
        <div style="font-weight:600;font-size:12.5px;">${f.cause}</div>
        <div class="text-secondary" style="font-size:12px;margin:2px 0 4px 0;">${f.detail}</div>
        <div class="text-muted" style="font-size:11px;">Suggestions: ${(f.suggestions||[]).join("; ")}</div>
      </div>
    `).join("")}
  </div>`;
}

// ================= SCENARIOS =================
const SCENARIO_FIELDS = [
  { key: "name", label: "Name", type: "text", required: true, placeholder: "e.g. Monsoon Shortage, Winter Peak Demand" },
  { key: "description", label: "Description", type: "text", placeholder: "e.g. Annual monsoon disruption to domestic gas fields" },
  { key: "probability", label: "Probability (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.2, 0.35, 0.5" },
  { key: "is_default", label: "Include in comparisons/stochastic", type: "checkbox", default: true },
  { key: "demand_multiplier", label: "Demand ×", type: "number", step: "0.01", default: 1.0, placeholder: "e.g. 1.0, 1.15, 1.3" },
  { key: "pipeline_capacity_multiplier", label: "Pipeline capacity ×", type: "number", step: "0.01", default: 1.0, placeholder: "e.g. 0.85, 0.95, 1.0" },
  { key: "transport_cost_multiplier", label: "Transport cost ×", type: "number", step: "0.01", default: 1.0, placeholder: "e.g. 1.0, 1.1, 1.25" },
];

async function loadScenarios() {
  const scenarios = await api.get(`/api/scenarios/${PROJECT_ID}`);
  const tbody = document.querySelector('#scenarioTable tbody');
  tbody.innerHTML = scenarios.map(s => `
    <tr>
      <td class="text-cell">${s.name}</td>
      <td>${fmtPct(s.probability)}</td>
      <td>${s.is_default ? '✓' : '—'}</td>
      <td>${s.demand_multiplier}</td>
      <td>${s.pipeline_capacity_multiplier}</td>
      <td>${s.transport_cost_multiplier}</td>
      <td><button class="btn ghost small danger" data-id="${s.id}">delete</button></td>
    </tr>
  `).join('') || `<tr><td colspan="7" class="text-secondary text-cell">No scenarios yet.</td></tr>`;
  tbody.querySelectorAll('button[data-id]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm('Delete this scenario?')) return;
      await api.delete(`/api/scenarios/${PROJECT_ID}/${btn.dataset.id}`);
      toast('Scenario deleted', 'ok');
      loadScenarios();
      populateScenarioDropdown();
    });
  });
  return scenarios;
}

document.getElementById('addScenarioBtn').addEventListener('click', () => {
  const wrap = document.getElementById('scenarioFormWrap');
  wrap.style.display = 'block';
  wrap.innerHTML = `<div class="card" style="background:var(--surface);">
    <form id="scenarioForm" style="display:flex;flex-wrap:wrap;gap:12px;align-items:end;">
      ${SCENARIO_FIELDS.map(f => `
        <div class="field" style="min-width:160px;">
          <label>${f.label}${f.required ? ' *' : ''}</label>
          ${f.type === 'checkbox' ? `<input type="checkbox" name="${f.key}" ${f.default ? 'checked' : ''} style="width:auto;">` :
            `<input type="${f.type}" name="${f.key}" step="${f.step||''}" value="${f.default && f.type !== 'text' ? f.default : ''}" placeholder="${f.placeholder || f.label}">`}
        </div>`).join('')}
      <div class="field" style="min-width:auto;">
        <button class="btn primary small" type="submit">Add</button>
        <button class="btn ghost small" type="button" id="cancelScenario">Cancel</button>
      </div>
    </form>
  </div>`;
  document.getElementById('cancelScenario').addEventListener('click', () => wrap.style.display = 'none');
  document.getElementById('scenarioForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = {};
    for (const f of SCENARIO_FIELDS) {
      const el = e.target.querySelector(`[name="${f.key}"]`);
      data[f.key] = f.type === 'checkbox' ? el.checked : (f.type === 'number' ? parseFloat(el.value) : el.value);
    }
    try {
      await api.post(`/api/scenarios/${PROJECT_ID}`, data);
      wrap.style.display = 'none';
      loadScenarios();
      populateScenarioDropdown();
      toast('Scenario added', 'ok');
    } catch (err) { toast(err.message, 'error'); }
  });
});

document.getElementById('runComparisonBtn').addEventListener('click', async () => {
  const box = document.getElementById('comparisonResult');
  box.innerHTML = '<p class="text-muted">Running…</p>';
  try {
    const res = await api.post(`/api/optimize/${PROJECT_ID}/compare-scenarios`, {});
    const rows = res.comparison;
    const baseline = rows.find(r => r.status === 'optimal');
    box.innerHTML = `<table class="data-table"><thead><tr>
        <th>Scenario</th><th>Prob.</th><th>Status</th><th>Total Cost</th><th>Fulfilment</th><th>Unmet</th><th>CGS Util</th><th>Station Util</th>
      </tr></thead><tbody>
      ${rows.map(r => {
        const deteriorated = baseline && r.status === 'optimal' && r.total_cost > baseline.total_cost * 1.001;
        return `<tr style="${deteriorated ? 'background:rgba(224,87,76,0.06);' : ''}">
          <td class="text-cell">${r.scenario_name}</td>
          <td>${fmtPct(r.probability)}</td>
          <td>${statusBadge(r.status)}</td>
          <td>${r.total_cost !== undefined ? fmtNum(r.total_cost, 0) : '—'}</td>
          <td>${r.fulfilment_pct !== undefined ? fmtPct(r.fulfilment_pct) : '—'}</td>
          <td>${r.unmet_demand !== undefined ? fmtNum(r.unmet_demand) : '—'}</td>
          <td>${r.avg_cgs_utilization !== undefined ? fmtPct(r.avg_cgs_utilization) : '—'}</td>
          <td>${r.avg_station_utilization !== undefined ? fmtPct(r.avg_station_utilization) : '—'}</td>
        </tr>` + (r.status === 'infeasible' ? `<tr><td colspan="8">${diagnosticsHTML({findings: r.diagnostics})}</td></tr>` : '');
      }).join('')}
      </tbody></table>`;
    toast('Scenario comparison complete', 'ok');
  } catch (err) { box.innerHTML = `<p style="color:var(--critical);">${err.message}</p>`; toast(err.message, 'error'); }
});

// ================= OPTIMIZE =================
async function populateScenarioDropdown() {
  const scenarios = await api.get(`/api/scenarios/${PROJECT_ID}`);
  const sel = document.getElementById('optScenario');
  sel.innerHTML = '<option value="">— base network, no scenario —</option>' +
    scenarios.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
}

const OPT_MODE_HINTS = {
  deterministic: "Solves the network exactly as configured, or against one selected scenario's overrides.",
  stochastic: "One solve, shared facility decisions, but flows adapt per scenario — minimizes the probability-weighted expected cost across all default scenarios at once.",
  robust: "Ignores scenario probabilities entirely; solves against a single worst-case supply-availability assumption you choose below.",
};
document.getElementById('optMode').addEventListener('change', (e) => {
  document.getElementById('optScenarioField').style.display = e.target.value === 'deterministic' ? 'block' : 'none';
  document.getElementById('robustFields').style.display = e.target.value === 'robust' ? 'block' : 'none';
  document.getElementById('optModeHint').textContent = OPT_MODE_HINTS[e.target.value] || '';
});

async function loadSolverDetail() {
  const info = await api.get('/api/meta/solvers');
  document.getElementById('solverDetail').innerHTML = info.solvers.map(s => `
    <div style="display:flex;justify-content:space-between;border-bottom:1px solid var(--border-soft);padding:4px 0;">
      <span>${s.name} <span class="text-muted">(${s.kind})</span></span>
      <span style="color:${s.available ? 'var(--ok)' : 'var(--text-muted)'};">${s.available ? 'available' : 'not found'}</span>
    </div>`).join('');
}

function renderOptResult(result) {
  const box = document.getElementById('optResults');
  if (result.status === 'solver_unavailable') {
    box.innerHTML = `<div class="card"><p style="color:var(--critical);">No solver available. ${result.solver_name || ''}</p></div>`;
    return;
  }
  if (result.status === 'infeasible') {
    box.innerHTML = `<div class="card">
      <div class="card-title">Infeasible ${statusBadge('infeasible')}</div>
      ${diagnosticsHTML(result.diagnostics)}
    </div>`;
    return;
  }
  if (result.status !== 'optimal' && !result.expected_cost) {
    box.innerHTML = `<div class="card"><p>Status: ${statusBadge(result.status)}</p></div>`;
    return;
  }

  // stochastic vs deterministic result shapes
  if (result.expected_cost !== undefined) {
    box.innerHTML = `
      <div class="grid cols-4" style="margin-bottom:16px;">
        <div class="kpi ok"><div class="label">Expected Cost</div><div class="value">${fmtNum(result.expected_cost,0)}</div></div>
        <div class="kpi warn"><div class="label">Worst-Case Cost</div><div class="value">${fmtNum(result.worst_case_cost,0)}</div></div>
        <div class="kpi"><div class="label">CGS Open</div><div class="value">${result.facilities.cgs.filter(f=>f.open).length}/${result.facilities.cgs.length}</div></div>
        <div class="kpi"><div class="label">Stations Open</div><div class="value">${result.facilities.stations.filter(f=>f.open).length}/${result.facilities.stations.length}</div></div>
      </div>
      <div class="card">
        <div class="card-title">Per-Scenario Recourse</div>
        <table class="data-table"><thead><tr><th>Scenario</th><th>Prob.</th><th>Cost</th><th>Fulfilment</th><th>Unmet</th></tr></thead>
        <tbody>${result.scenario_results.map(r => `<tr>
          <td class="text-cell">${r.scenario}</td><td>${fmtPct(r.probability)}</td><td>${fmtNum(r.total_cost,0)}</td>
          <td>${fmtPct(r.fulfilment_pct)}</td><td>${fmtNum(r.total_unmet)}</td></tr>`).join('')}</tbody></table>
      </div>`;
    return;
  }

  const cb = result.cost_breakdown;
  box.innerHTML = `
    <div class="grid cols-4" style="margin-bottom:16px;">
      <div class="kpi ok"><div class="label">Total Cost</div><div class="value">${fmtNum(result.objective_value,0)}</div></div>
      <div class="kpi"><div class="label">Demand Fulfilment</div><div class="value">${fmtPct(result.kpis.demand_fulfilment_pct)}</div></div>
      <div class="kpi ${result.kpis.total_unmet_demand > 0 ? 'warn' : 'ok'}"><div class="label">Unmet Demand</div><div class="value">${fmtNum(result.kpis.total_unmet_demand)}</div></div>
      <div class="kpi"><div class="label">Facilities Open</div><div class="value" style="font-size:16px;">${result.kpis.cgs_open_count}/${result.kpis.cgs_total_count} CGS · ${result.kpis.station_open_count}/${result.kpis.station_total_count} STN</div></div>
    </div>
    <div class="grid cols-2" style="margin-bottom:16px;">
      <div class="card">
        <div class="card-title">Cost Breakdown</div>
        <table class="data-table"><tbody>
          ${Object.entries(cb).map(([k,v]) => `<tr><td class="text-cell" style="text-transform:capitalize;">${k.replace('_',' ')}</td><td>${fmtNum(v,0)}</td></tr>`).join('')}
        </tbody></table>
      </div>
      <div class="card">
        <div class="card-title">Facility Utilization</div>
        <table class="data-table"><thead><tr><th>Code</th><th>Type</th><th>Open</th><th>Util</th></tr></thead><tbody>
          ${[...result.facilities.cgs.map(f=>({...f,type:'CGS'})), ...result.facilities.stations.map(f=>({...f,type:'STN'}))]
            .map(f => `<tr><td class="text-cell">${f.code}</td><td>${f.type}</td><td>${f.open?'yes':'no'}</td>
              <td><span class="badge ${f.utilization>=0.9?'critical':(f.utilization>=0.7?'warn':'ok')}">${fmtPct(f.utilization)}</span></td></tr>`).join('')}
        </tbody></table>
      </div>
    </div>
    ${result.contract_shortfalls && result.contract_shortfalls.length ? `
    <div class="card" style="margin-bottom:16px;">
      <div class="card-title">Take-or-Pay Shortfalls</div>
      <p class="text-muted" style="font-size:11.5px;margin-top:-6px;">Sources that took less than their contracted quantity still get billed a penalty on the gap — a real take-or-pay contract term, not a modeling artifact.</p>
      <table class="data-table"><thead><tr><th>Source</th><th>Contracted</th><th>Shortfall</th><th>Penalty Rate</th></tr></thead><tbody>
        ${result.contract_shortfalls.map(s => `<tr><td class="text-cell">${s.source}</td><td>${fmtNum(s.contracted_quantity)}</td><td>${fmtNum(s.shortfall)}</td><td>${fmtNum(s.penalty_rate,2)}</td></tr>`).join('')}
      </tbody></table>
    </div>` : ''}
    <div class="card">
      <div class="card-title">Demand Zones</div>
      <table class="data-table"><thead><tr><th>Zone</th><th>Priority</th><th>Demand</th><th>Unmet</th><th>Fulfilment</th></tr></thead><tbody>
        ${result.demand_results.map(d => `<tr style="${d.unmet>0?'background:rgba(224,87,76,0.06);':''}">
          <td class="text-cell">${d.code}</td><td class="text-cell">${d.priority}</td><td>${fmtNum(d.demand)}</td>
          <td>${fmtNum(d.unmet)}</td><td>${fmtPct(d.fulfilment_pct)}</td></tr>`).join('')}
      </tbody></table>
    </div>`;
}

document.getElementById('runOptBtn').addEventListener('click', async () => {
  const mode = document.getElementById('optMode').value;
  const progress = document.getElementById('optProgress');
  progress.textContent = 'Optimization running…';
  document.getElementById('optResults').innerHTML = '';
  try {
    let result;
    if (mode === 'deterministic') {
      const scenarioId = document.getElementById('optScenario').value;
      result = await api.post(`/api/optimize/${PROJECT_ID}`, scenarioId ? { scenario_id: parseInt(scenarioId) } : {});
    } else if (mode === 'stochastic') {
      result = await api.post(`/api/optimize/${PROJECT_ID}/stochastic`, {});
    } else {
      result = await api.post(`/api/optimize/${PROJECT_ID}/robust`, {
        mode: document.getElementById('robustMode').value,
        supply_range: [parseFloat(document.getElementById('robustLo').value), parseFloat(document.getElementById('robustHi').value)],
      });
    }
    progress.innerHTML = `Solver: ${result.solver_name || '—'} &nbsp; Variables: ${result.num_variables ?? '—'} &nbsp; Constraints: ${result.num_constraints ?? '—'} &nbsp; Runtime: ${result.runtime_seconds ?? '—'}s &nbsp; Status: ${result.status}`;
    renderOptResult(result);
    if (result.status === 'optimal') toast('Optimization complete', 'ok');
    else if (result.status === 'infeasible') toast('No feasible solution found — see details below', 'error');
  } catch (err) {
    progress.textContent = '';
    toast(err.message, 'error');
  }
});

// ================= SIMULATE =================
let PRESETS = [];
async function loadPresets() {
  PRESETS = await api.get(`/api/scenarios/${PROJECT_ID}/presets`);
  document.getElementById('presetButtons').innerHTML = PRESETS.map(p =>
    `<button class="btn small" data-preset="${p.key}" title="${p.hint || ''}">${p.label}</button>`).join('');
  document.querySelectorAll('#presetButtons button').forEach(btn => {
    btn.addEventListener('click', () => runWhatif(btn.dataset.preset));
  });
}

function whatifSummaryCard(label, s) {
  if (!s || s.status !== 'optimal') return `<div class="card"><div class="card-title">${label}</div><p>${statusBadge(s ? s.status : 'n/a')}</p></div>`;
  return `<div class="card">
    <div class="card-title">${label}</div>
    <div class="kpi" style="border-left-color:var(--accent);margin-bottom:8px;"><div class="label">Total Cost</div><div class="value">${fmtNum(s.total_cost,0)}</div></div>
    <div class="text-secondary" style="font-size:12px;line-height:1.8;">
      Fulfilment: <b class="mono">${fmtPct(s.fulfilment_pct)}</b><br>
      Unmet demand: <b class="mono">${fmtNum(s.unmet_demand)}</b><br>
      CGS open: <b class="mono">${s.cgs_open}</b> &nbsp; Stations open: <b class="mono">${s.stations_open}</b><br>
      Avg CGS util: <b class="mono">${fmtPct(s.avg_cgs_utilization)}</b> &nbsp; Avg station util: <b class="mono">${fmtPct(s.avg_station_utilization)}</b>
    </div>
  </div>`;
}

async function runWhatif(presetKey) {
  const box = document.getElementById('whatifResult');
  box.innerHTML = '<p class="text-muted">Running before/after comparison…</p>';
  try {
    const res = await api.post(`/api/whatif/${PROJECT_ID}`, { preset: presetKey });
    let deltaHTML = '';
    if (res.delta) {
      const costColor = res.delta.cost_change > 0 ? 'var(--warn)' : 'var(--ok)';
      deltaHTML = `<div class="card">
        <div class="card-title">Impact</div>
        <div class="kpi" style="border-left-color:${costColor};margin-bottom:8px;">
          <div class="label">Cost Change</div>
          <div class="value">${res.delta.cost_change >= 0 ? '+' : ''}${fmtNum(res.delta.cost_change,0)}</div>
          <div class="sub">${res.delta.cost_change_pct >= 0 ? '+' : ''}${res.delta.cost_change_pct}%</div>
        </div>
        <div class="text-secondary" style="font-size:12px;line-height:1.8;">
          Fulfilment change: <b class="mono">${res.delta.fulfilment_change_pct_points >= 0 ? '+' : ''}${res.delta.fulfilment_change_pct_points} pts</b><br>
          Unmet demand change: <b class="mono">${res.delta.unmet_demand_change >= 0 ? '+' : ''}${fmtNum(res.delta.unmet_demand_change)}</b>
        </div>
      </div>`;
    }
    box.innerHTML = `<div class="grid cols-3">
      ${whatifSummaryCard('Before', res.before)}
      ${whatifSummaryCard('After', res.after)}
      ${deltaHTML || '<div class="card"><div class="card-title">Impact</div><p class="text-muted">Not applicable (infeasible result).</p></div>'}
    </div>` + (res.after.diagnostics ? `<div class="card" style="margin-top:12px;">${diagnosticsHTML({findings: res.after.diagnostics})}</div>` : '');
    toast('Comparison ready', 'ok');
  } catch (err) { box.innerHTML = `<p style="color:var(--critical);">${err.message}</p>`; toast(err.message, 'error'); }
}

let simChartInstance = null;
document.getElementById('runSimBtn').addEventListener('click', async () => {
  const periods = parseInt(document.getElementById('simPeriods').value || 5);
  try {
    const res = await api.post(`/api/simulate/${PROJECT_ID}`, { num_periods: periods });
    const optimalPeriods = res.periods.filter(p => p.status === 'optimal');
    if (chartsAvailable()) {
      const ctx = document.getElementById('simChart').getContext('2d');
      if (simChartInstance) simChartInstance.destroy();
      simChartInstance = new Chart(ctx, {
        type: 'line',
      data: {
        labels: res.periods.map(p => 'T' + p.period),
        datasets: [
          { label: 'Total Cost', data: res.periods.map(p => p.total_cost ?? null), borderColor: '#33b1c9', yAxisID: 'y', tension: 0.2 },
          { label: 'Unmet Demand', data: res.periods.map(p => p.unmet_demand ?? null), borderColor: '#e0574c', yAxisID: 'y1', tension: 0.2 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          y: { position: 'left', title: { display: true, text: 'Cost', color: '#51687e' }, ticks: { color: '#51687e' }, grid: { color: '#e7ecf1' } },
          y1: { position: 'right', title: { display: true, text: 'Unmet Demand', color: '#51687e' }, ticks: { color: '#51687e' }, grid: { display: false } },
          x: { ticks: { color: '#51687e' }, grid: { color: '#e7ecf1' } },
        },
        plugins: { legend: { labels: { color: '#182430' } } },
      },
      });
    }
    document.getElementById('simTableWrap').innerHTML = `<table class="data-table"><thead><tr>
      <th>Period</th><th>Status</th><th>Demand</th><th>Supply Avail.</th><th>Unmet</th><th>Fulfilment</th><th>Cost</th></tr></thead><tbody>
      ${res.periods.map(p => `<tr>
        <td>${p.period}</td><td>${statusBadge(p.status)}</td>
        <td>${fmtNum(p.total_demand)}</td><td>${fmtNum(p.total_supply_available)}</td>
        <td>${fmtNum(p.unmet_demand)}</td><td>${fmtPct(p.fulfilment_pct)}</td><td>${fmtNum(p.total_cost,0)}</td>
      </tr>`).join('')}</tbody></table>`;
    toast('Timeline simulation complete', 'ok');
  } catch (err) { toast(err.message, 'error'); }
});

// ================= ANALYZE =================
let paretoChartInstance = null;
let tornadoChartInstance = null;

async function loadAnalyzePanel(panel) {
  const el = document.getElementById('analyzePanel');
  el.innerHTML = '<p class="text-muted">Loading…</p>';
  try {
    if (panel === 'resilience') {
      const res = await api.get(`/api/analytics/${PROJECT_ID}/resilience`);
      el.innerHTML = `
        <div class="card-title">Resilience Score</div>
        <div class="kpi ok" style="max-width:220px;margin-bottom:16px;"><div class="label">Overall</div><div class="value">${res.score}<span class="unit">/100</span></div></div>
        <table class="data-table"><thead><tr><th>Component</th><th>Weight</th><th>Score</th></tr></thead><tbody>
          ${Object.entries(res.components).map(([k,v]) => `<tr>
            <td class="text-cell">${res.component_labels[k]}</td><td>${fmtPct(res.weights[k])}</td><td>${fmtPct(v)}</td></tr>`).join('')}
        </tbody></table>
        <p class="text-muted" style="font-size:11px;margin-top:10px;">Weights are configurable — this is a transparent weighted sum of real network metrics, not a black-box score.</p>`;
    }

    if (panel === 'pareto') {
      const res = await api.get(`/api/analytics/${PROJECT_ID}/pareto`);
      el.innerHTML = `<div class="card-title">Cost vs. Service Level</div>
        <div style="height:280px;"><canvas id="paretoChart"></canvas></div>
        <div class="grid cols-3" style="margin-top:16px;">
          <div class="kpi"><div class="label">Cost-Optimal</div><div class="value" style="font-size:16px;">SL ${res.cost_optimal_point ? fmtPct(res.cost_optimal_point.service_level) : '—'}</div></div>
          <div class="kpi"><div class="label">Resilience-Optimal</div><div class="value" style="font-size:16px;">SL ${res.resilience_optimal_point ? fmtPct(res.resilience_optimal_point.service_level) : '—'}</div></div>
          <div class="kpi ok"><div class="label">Balanced</div><div class="value" style="font-size:16px;">SL ${res.balanced_point ? fmtPct(res.balanced_point.service_level) : '—'}</div></div>
        </div>`;
      if (chartsAvailable()) {
        const ctx = document.getElementById('paretoChart').getContext('2d');
        if (paretoChartInstance) paretoChartInstance.destroy();
        paretoChartInstance = new Chart(ctx, {
          type: 'line',
          data: { labels: res.points.map(p => fmtPct(p.service_level)),
            datasets: [{ label: 'Min Cost', data: res.points.map(p => p.cost), borderColor: '#33b1c9', backgroundColor: '#33b1c933', tension: 0.15, fill: true }] },
          options: { responsive: true, maintainAspectRatio: false,
            scales: { y: { ticks: { color: '#51687e' }, grid: { color: '#e7ecf1' } }, x: { ticks: { color: '#51687e' }, grid: { color: '#e7ecf1' } } },
            plugins: { legend: { labels: { color: '#182430' } } } },
        });
      }
    }

    if (panel === 'sensitivity') {
      const res = await api.get(`/api/analytics/${PROJECT_ID}/tornado`);
      if (res.error) { el.innerHTML = `<p style="color:var(--critical);">${res.error}</p>`; return; }
      el.innerHTML = `<div class="card-title">Tornado Chart — Cost Impact of ±${res.delta_pct*100}% Parameter Change</div>
        <div style="height:${res.rows.length * 40 + 40}px;"><canvas id="tornadoChart"></canvas></div>`;
      if (chartsAvailable()) {
        const ctx = document.getElementById('tornadoChart').getContext('2d');
        if (tornadoChartInstance) tornadoChartInstance.destroy();
        tornadoChartInstance = new Chart(ctx, {
          type: 'bar',
          data: { labels: res.rows.map(r => r.label),
            datasets: [
              { label: 'Low', data: res.rows.map(r => r.cost_delta_low), backgroundColor: '#e3a63c' },
              { label: 'High', data: res.rows.map(r => r.cost_delta_high), backgroundColor: '#33b1c9' },
            ] },
          options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
            scales: { x: { ticks: { color: '#51687e' }, grid: { color: '#e7ecf1' } }, y: { ticks: { color: '#51687e' }, grid: { color: '#e7ecf1' } } },
            plugins: { legend: { labels: { color: '#182430' } } } },
        });
      }
    }

    if (panel === 'heatmap') {
      const res = await api.get(`/api/analytics/${PROJECT_ID}/heatmap`);
      const maxCost = Math.max(...res.grid.flat().map(c => c.cost || 0));
      el.innerHTML = `<div class="card-title">${res.y_label} × ${res.x_label} — Cost Heatmap</div>
        <table class="data-table"><thead><tr><th></th>${res.x_values.map(x => `<th>${x}</th>`).join('')}</tr></thead><tbody>
          ${res.grid.map((row, i) => `<tr><td class="text-cell">${res.y_values[i]}</td>
            ${row.map(c => {
              const intensity = c.cost ? Math.round((c.cost / maxCost) * 60 + 10) : 0;
              const bg = c.status === 'optimal' ? `rgba(224,87,76,${c.unmet_demand > 0 ? 0.25 : intensity/150})` : 'rgba(224,87,76,0.5)';
              return `<td style="background:${bg};">${c.status === 'optimal' ? fmtNum(c.cost,0) : 'infeasible'}</td>`;
            }).join('')}
          </tr>`).join('')}
        </tbody></table>
        <p class="text-muted" style="font-size:11px;margin-top:8px;">Darker red = higher cost or unmet demand present.</p>`;
    }

    if (panel === 'recommendations') {
      const res = await api.get(`/api/analytics/${PROJECT_ID}/recommendations`);
      el.innerHTML = `<div class="card-title">Recommendations</div>` +
        (res.recommendations.length ? res.recommendations.map(r => `
          <div style="padding:10px 0;border-bottom:1px solid var(--border-soft);">
            <div style="font-weight:600;font-size:13px;">${r.title}</div>
            <div class="text-secondary" style="font-size:12.5px;margin:4px 0;">${r.reason}</div>
            <details><summary style="cursor:pointer;font-size:11px;color:var(--accent);">Why?</summary>
              <pre class="mono" style="font-size:11px;color:var(--text-muted);white-space:pre-wrap;">${JSON.stringify(r.why, null, 2)}</pre>
            </details>
          </div>`).join('') : '<p class="text-muted">No recommendations triggered by the current network.</p>');
    }
  } catch (err) {
    el.innerHTML = `<p style="color:var(--critical);">${err.message}</p>`;
  }
}

document.querySelectorAll('#analyzeTabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#analyzeTabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    loadAnalyzePanel(tab.dataset.panel);
  });
});

// ================= REPORT =================
let reportMode = 'industry';
document.querySelectorAll('#reportModeTabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#reportModeTabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    reportMode = tab.dataset.mode;
    loadReportPanel();
  });
});

async function loadReportPanel() {
  const el = document.getElementById('reportPanel');
  el.innerHTML = '<p class="text-muted">Loading…</p>';
  try {
    if (reportMode === 'industry') {
      const res = await api.get(`/api/report/${PROJECT_ID}/executive`);
      const r = res.normal_result;
      el.innerHTML = `
        <div class="card-title">Executive Summary</div>
        <p class="text-secondary" style="font-size:12.5px;">${res.problem_statement}</p>
        ${r.status === 'optimal' ? `
        <div class="grid cols-4" style="margin:14px 0;">
          <div class="kpi ok"><div class="label">Total Cost</div><div class="value">${fmtNum(r.objective_value,0)}</div></div>
          <div class="kpi"><div class="label">Fulfilment</div><div class="value">${fmtPct(r.kpis.demand_fulfilment_pct)}</div></div>
          <div class="kpi"><div class="label">Unmet</div><div class="value">${fmtNum(r.kpis.total_unmet_demand)}</div></div>
          <div class="kpi"><div class="label">Resilience</div><div class="value">${res.resilience ? res.resilience.score : '—'}<span class="unit">/100</span></div></div>
        </div>` : `<p>${statusBadge(r.status)}</p>`}
        <div class="card-title" style="margin-top:10px;">Recommendations</div>
        ${res.recommendations.length ? res.recommendations.map(rec => `<div style="padding:6px 0;border-bottom:1px solid var(--border-soft);font-size:12.5px;">
          <b>${rec.title}</b> — <span class="text-secondary">${rec.reason}</span></div>`).join('') : '<p class="text-muted">None triggered.</p>'}
        ${res.project.is_demo ? `<p class="tag-illustrative" style="margin-top:14px;">${res.data_quality_note}</p>` : ''}
      `;
    } else {
      const res = await api.get(`/api/report/${PROJECT_ID}/technical`);
      el.innerHTML = `
        <div class="card-title">Mathematical Formulation</div>
        <table class="data-table"><tbody>
          ${Object.entries(res.sets).map(([k,v]) => `<tr><td class="text-cell">${k}</td><td>${v}</td></tr>`).join('')}
        </tbody></table>
        <div class="card-title" style="margin-top:14px;">Decision Variables</div>
        <table class="data-table"><tbody>
          ${res.decision_variables.map(v => `<tr><td class="mono">${v.name}</td><td class="text-cell">${v.type}</td><td class="text-cell">${v.description}</td></tr>`).join('')}
        </tbody></table>
        <div class="card-title" style="margin-top:14px;">Objective</div>
        <p class="text-secondary" style="font-size:12.5px;">${res.objective}</p>
        <div class="card-title" style="margin-top:14px;">Constraints</div>
        <ul style="font-size:12.5px;color:var(--text-secondary);">${res.constraints.map(c => `<li>${c}</li>`).join('')}</ul>
        <div class="card-title" style="margin-top:14px;">Solver &amp; Model Size</div>
        <p class="mono" style="font-size:12.5px;">Solver: ${res.solver} · Variables: ${res.model_size.variables} · Constraints: ${res.model_size.constraints} · Status: ${res.solve_status}</p>
      `;
    }
  } catch (err) { el.innerHTML = `<p style="color:var(--critical);">${err.message}</p>`; }
}

document.querySelectorAll('[data-fmt]').forEach(btn => {
  btn.addEventListener('click', () => {
    toast(`Preparing ${btn.dataset.fmt.toUpperCase()} export…`, 'info');
    window.location.href = `/api/report/${PROJECT_ID}/export/${btn.dataset.fmt}`;
  });
});

// ================= dashboard: full summary =================
const summaryBtn = document.getElementById('runSummaryBtn');
if (summaryBtn) {
  summaryBtn.addEventListener('click', async () => {
    const panel = document.getElementById('summaryPanel');
    panel.innerHTML = '<p class="text-muted">Solving normal + severe scenarios…</p>';
    try {
      const s = await api.get(`/api/analytics/${PROJECT_ID}/summary`);
      panel.innerHTML = `
        <div class="grid cols-4" style="margin-bottom:14px;">
          <div class="kpi ok"><div class="label">Total Investment</div><div class="value">${fmtNum(s.total_investment,0)}</div></div>
          <div class="kpi"><div class="label">Normal Service</div><div class="value">${fmtPct(s.normal_scenario.service_level_pct)}</div></div>
          <div class="kpi ${s.severe_scenario.service_level_pct < 0.95 ? 'warn' : 'ok'}"><div class="label">Severe Scenario Service</div><div class="value">${s.severe_scenario.service_level_pct !== null ? fmtPct(s.severe_scenario.service_level_pct) : 'infeasible'}</div></div>
          <div class="kpi ${s.resilience_score >= 70 ? 'ok' : 'warn'}"><div class="label">Resilience Score</div><div class="value">${s.resilience_score}<span class="unit">/100</span></div></div>
        </div>
        <div class="grid cols-2" style="margin-bottom:14px;">
          <div class="kpi"><div class="label">Unmet Demand (Normal)</div><div class="value">${fmtNum(s.unmet_demand)}</div></div>
          <div class="kpi ${s.critical_bottlenecks > 0 ? 'critical' : 'ok'}"><div class="label">Critical Bottlenecks</div><div class="value">${s.critical_bottlenecks ?? '—'}</div></div>
        </div>
        <div class="card-title">Top Recommendations</div>
        ${s.top_recommendations.length ? s.top_recommendations.map((r,i) => `<div style="padding:6px 0;border-bottom:1px solid var(--border-soft);font-size:12.5px;"><b>${i+1}. ${r.title}</b> — <span class="text-secondary">${r.reason}</span></div>`).join('') : '<p class="text-muted">None triggered.</p>'}
      `;
      toast('Analysis complete', 'ok');
    } catch (err) { document.getElementById('summaryPanel').innerHTML = `<p style="color:var(--critical);">${err.message}</p>`; toast(err.message, 'error'); }
  });
}

// ================= wire into section navigation =================
const _origShowSection = window.showSection;
window.showSection = function(name) {
  _origShowSection(name);
  if (name === 'scenarios') loadScenarios();
  if (name === 'optimize') { populateScenarioDropdown(); loadSolverDetail(); }
  if (name === 'simulate') loadPresets();
  if (name === 'analyze') loadAnalyzePanel(document.querySelector('#analyzeTabs .tab.active').dataset.panel);
  if (name === 'report') loadReportPanel();
};
