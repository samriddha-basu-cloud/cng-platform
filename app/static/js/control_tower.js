/* Control Tower tab: executive KPIs + alerts (spec 34-36), bottleneck +
   marginal value analysis (spec 19-20), investment decision support
   (spec 22/84), and run comparison (spec 60). Every number comes from a
   real solve — nothing here is a static threshold applied to a fake value. */

async function renderControlTowerSection() {
  const panel = document.getElementById('controlTowerPanel');
  const sub = document.querySelector('#controlTowerTabs .tab.active').dataset.panel;
  if (sub === 'kpis') return renderKpiAlertsPanel(panel);
  if (sub === 'bottlenecks') return renderBottlenecksPanel(panel);
  if (sub === 'investment') return renderInvestmentPanel(panel);
  if (sub === 'compare') return renderRunComparePanel(panel);
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('#controlTowerTabs .tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('#controlTowerTabs .tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      renderControlTowerSection();
    });
  });
});

const SEV_COLOR = { CRITICAL: 'critical', WARNING: 'warn', INFO: 'ok' };

// --------------------------------------------------------- KPIs + alerts ---
async function renderKpiAlertsPanel(panel) {
  panel.innerHTML = `<div class="card mono text-muted" id="ctKpiWrap">Loading…</div>`;
  const wrap = document.getElementById('ctKpiWrap');
  try {
    const data = await api.get(`/api/analytics/${PROJECT_ID}/control-tower`);
    if (data.status !== 'optimal') {
      wrap.innerHTML = `<span style="color:var(--critical);">Could not solve: ${data.status}</span>`;
      return;
    }
    const k = data.kpis;
    const kpiCards = [
      ['Total Demand', k.total_demand], ['Total Shortage', k.total_shortage],
      ['Overall Service Level', (k.overall_service_level * 100).toFixed(1) + '%'],
      ['Total Cost', k.total_cost?.toLocaleString()], ['Expansion CAPEX', k.expansion_capex?.toLocaleString()],
      ['Months with Shortage', `${k.months_with_shortage}/${k.horizon_months}`],
      ['CGS Open', k.cgs_open_count], ['Stations Open', k.station_open_count],
      ['Critical Bottlenecks', k.critical_bottleneck_count],
    ];
    const kpiHtml = kpiCards.map(([label, value]) => `
      <div class="kpi"><div class="label">${label}</div><div class="value">${value}</div></div>
    `).join('');

    const tierRows = data.tier_service_levels.map(t => `
      <tr class="${t.below_target ? 'row-critical' : ''}">
        <td>${t.tier}</td><td>${t.rank ?? '-'}</td><td>${(t.service_level * 100).toFixed(1)}%</td>
        <td>${t.target != null ? (t.target * 100).toFixed(0) + '%' : '-'}</td>
        <td>${t.below_target ? '<span class="badge critical">below target</span>' : '<span class="badge ok">on target</span>'}</td>
      </tr>
    `).join('');

    const alertRows = data.alerts.map(a => `
      <tr>
        <td><span class="badge ${SEV_COLOR[a.severity] || 'warn'}">${a.severity}</span></td>
        <td class="mono">${a.asset}</td><td>${a.metric}</td>
        <td>${a.reason}</td><td>${a.recommended_action}</td>
      </tr>
    `).join('');

    wrap.innerHTML = `
      <div class="grid cols-4" style="margin-bottom:18px;">${kpiHtml}</div>
      <div style="font-weight:600;font-size:12.5px;margin-bottom:6px;">Tier Service Levels</div>
      <table class="data-table" style="margin-bottom:18px;">
        <thead><tr><th>Tier</th><th>Rank</th><th>Service Level</th><th>Target</th><th>Status</th></tr></thead>
        <tbody>${tierRows || '<tr><td colspan="5">No priority tiers configured.</td></tr>'}</tbody>
      </table>
      <div style="font-weight:600;font-size:12.5px;margin-bottom:6px;">Alerts</div>
      <table class="data-table">
        <thead><tr><th>Severity</th><th>Asset</th><th>Metric</th><th>Reason</th><th>Recommended Action</th></tr></thead>
        <tbody>${alertRows || '<tr><td colspan="5">No alerts — network is healthy.</td></tr>'}</tbody>
      </table>
    `;
  } catch (e) {
    wrap.innerHTML = `<span style="color:var(--critical);">${e.message}</span>`;
  }
}

// --------------------------------------------------------- bottlenecks -----
async function renderBottlenecksPanel(panel) {
  panel.innerHTML = `<div class="card mono text-muted" id="ctBottleneckWrap">Loading…</div>`;
  const wrap = document.getElementById('ctBottleneckWrap');
  try {
    const data = await api.get(`/api/analytics/${PROJECT_ID}/bottlenecks`);
    const critRows = data.critical.map(c => `
      <tr>
        <td class="mono">${c.asset_code}</td><td>${c.asset_type}</td>
        <td>${c.months_binding}</td><td>${c.months_near_binding}</td>
        <td>${(c.avg_utilization * 100).toFixed(1)}%</td><td>${(c.max_utilization * 100).toFixed(1)}%</td>
        <td><span class="badge ${c.severity === 'HIGH' ? 'critical' : 'warn'}">${c.severity}</span></td>
      </tr>
    `).join('');
    const mvRows = (data.marginal_values || []).map(m => `
      <tr>
        <td class="mono">${m.asset_code}</td><td>${m.asset_type}</td><td>${m.month}</td>
        <td>${m.capacity}</td><td>${(m.utilization * 100).toFixed(1)}%</td>
        <td>${m.capacity_increment_tested}</td>
        <td style="font-weight:600;">${m.marginal_value_per_unit.toLocaleString()}</td>
      </tr>
    `).join('');

    wrap.innerHTML = `
      <div style="font-weight:600;font-size:12.5px;margin-bottom:6px;">Critical Bottlenecks</div>
      <table class="data-table" style="margin-bottom:18px;">
        <thead><tr><th>Asset</th><th>Type</th><th>Months Binding</th><th>Months Near-Binding</th>
        <th>Avg Util.</th><th>Max Util.</th><th>Severity</th></tr></thead>
        <tbody>${critRows || '<tr><td colspan="7">No binding or near-binding constraints found.</td></tr>'}</tbody>
      </table>
      <div style="font-weight:600;font-size:12.5px;margin-bottom:6px;">Marginal Value (finite-difference MILP resolve)</div>
      <p class="text-muted" style="font-size:11.5px;">
        Not an LP dual/shadow price — the model is a MILP. Each row is a full re-solve with that
        asset's capacity bumped by the increment shown, at its worst month; the value is the
        resulting drop in total cost per unit added.
      </p>
      <table class="data-table">
        <thead><tr><th>Asset</th><th>Type</th><th>Month</th><th>Capacity</th><th>Utilization</th>
        <th>Increment Tested</th><th>Marginal Value / Unit</th></tr></thead>
        <tbody>${mvRows || '<tr><td colspan="7">No marginal values computed.</td></tr>'}</tbody>
      </table>
    `;
  } catch (e) {
    wrap.innerHTML = `<span style="color:var(--critical);">${e.message}</span>`;
  }
}

// --------------------------------------------------------- investment ------
function renderInvestmentPanel(panel) {
  panel.innerHTML = `
    <div class="grid cols-2">
      <div class="card">
        <div class="card-title">Minimum CAPEX for Target Service Level</div>
        <div class="field"><label>Target service level (0-1)</label>
          <input type="number" id="invTargetService" step="0.01" min="0" max="1" value="0.95"></div>
        <button class="btn primary" id="runMinCapexBtn">Solve</button>
        <div id="minCapexResult" class="mono text-muted" style="margin-top:12px;font-size:12px;"></div>
      </div>
      <div class="card">
        <div class="card-title">Maximum Service Level for Fixed Budget</div>
        <div class="field"><label>Budget (CAPEX, currency)</label>
          <input type="number" id="invBudget" step="1" min="0" value="100"></div>
        <button class="btn primary" id="runMaxServiceBtn">Solve</button>
        <div id="maxServiceResult" class="mono text-muted" style="margin-top:12px;font-size:12px;"></div>
      </div>
    </div>
  `;
  document.getElementById('runMinCapexBtn').addEventListener('click', async () => {
    const el = document.getElementById('minCapexResult');
    el.textContent = 'Solving…';
    try {
      const target = parseFloat(document.getElementById('invTargetService').value || 0.95);
      const res = await api.post(`/api/optimize/${PROJECT_ID}/investment/min-capex`, { target_service_level: target });
      el.innerHTML = renderInvestmentResult(res, 'Minimum CAPEX');
    } catch (e) { el.innerHTML = `<span style="color:var(--critical);">${e.message}</span>`; }
  });
  document.getElementById('runMaxServiceBtn').addEventListener('click', async () => {
    const el = document.getElementById('maxServiceResult');
    el.textContent = 'Solving…';
    try {
      const budget = parseFloat(document.getElementById('invBudget').value || 0);
      const res = await api.post(`/api/optimize/${PROJECT_ID}/investment/max-service`, { budget });
      el.innerHTML = renderInvestmentResult(res, 'Max Service for Budget');
    } catch (e) { el.innerHTML = `<span style="color:var(--critical);">${e.message}</span>`; }
  });
}

function renderInvestmentResult(res, title) {
  if (res.status !== 'optimal') {
    return `<span style="color:var(--critical);">${title}: ${res.status}</span>` +
      (res.note ? `<div>${res.note}</div>` : '');
  }
  const expanded = [...res.facilities.cgs, ...res.facilities.stations].filter(f => f.expansion > 1e-6);
  const expansionRows = expanded.map(f => `<div>${f.code}: +${f.expansion.toFixed(1)} capacity</div>`).join('');
  return `
    <div style="color:var(--ok);">Optimal</div>
    <div>CAPEX: ${res.expansion_capex.toLocaleString()}</div>
    <div>Total cost: ${res.total_cost.toLocaleString()}</div>
    <div>Overall service level: ${(res.kpis.overall_service_level * 100).toFixed(1)}%</div>
    ${expansionRows ? `<div style="margin-top:6px;">Expansions:</div>${expansionRows}` : '<div>No expansion needed.</div>'}
  `;
}

// --------------------------------------------------------- run compare -----
async function renderRunComparePanel(panel) {
  panel.innerHTML = `
    <div class="card">
      <div class="card-title">Run Comparison</div>
      <div class="grid cols-2">
        <div class="field"><label>Run A</label><select id="runASelect"></select></div>
        <div class="field"><label>Run B</label><select id="runBSelect"></select></div>
      </div>
      <button class="btn primary" id="compareRunsBtn">Compare</button>
      <div id="runCompareResult" style="margin-top:16px;"></div>
    </div>
  `;
  const runs = await api.get(`/api/runs/${PROJECT_ID}`);
  const options = runs.map(r => `<option value="${r.id}">#${r.id} — ${r.run_type} — ${r.status} — ${new Date(r.created_at).toLocaleString()}</option>`).join('');
  document.getElementById('runASelect').innerHTML = options;
  document.getElementById('runBSelect').innerHTML = options;
  document.getElementById('compareRunsBtn').addEventListener('click', async () => {
    const a = document.getElementById('runASelect').value;
    const b = document.getElementById('runBSelect').value;
    const el = document.getElementById('runCompareResult');
    if (!a || !b) { toast('Need at least two stored runs to compare', 'error'); return; }
    try {
      const data = await api.get(`/api/runs/compare?run_a=${a}&run_b=${b}`);
      const rows = data.comparison.map(m => `
        <tr><td>${m.metric}</td><td>${m.run_a ?? '-'}</td><td>${m.run_b ?? '-'}</td>
        <td style="${m.delta > 0 ? 'color:var(--critical);' : m.delta < 0 ? 'color:var(--ok);' : ''}">${m.delta ?? '-'}</td></tr>
      `).join('');
      el.innerHTML = `
        <table class="data-table">
          <thead><tr><th>Metric</th><th>Run A (#${data.run_a.id}, ${data.run_a.run_type})</th>
          <th>Run B (#${data.run_b.id}, ${data.run_b.run_type})</th><th>Δ (B − A)</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    } catch (e) { el.innerHTML = `<span style="color:var(--critical);">${e.message}</span>`; }
  });
}
