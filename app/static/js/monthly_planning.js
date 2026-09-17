/* Monthly Planning tab: Excel import/export (spec sections 37-57), a
   12-month editable grid for supply/demand/corridor data (section 16), and
   the multi-period MILP's monthly allocation / supply-demand-balance
   dashboards (sections 16-17). Reuses the existing REST endpoints as-is -
   monthly dict fields (monthly_availability etc.) are just another field on
   the same entities the Network tab already edits via PATCH. */

const MONTHS = [1,2,3,4,5,6,7,8,9,10,11,12];
const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

const PLANNING_GRIDS = {
  sources: { label: "Sources — monthly available gas", field: "monthly_availability", flatField: "max_capacity", nameKey: "name" },
  demand: { label: "Demand Zones — monthly demand", field: "monthly_demand", flatField: "base_demand", nameKey: "name" },
  corridors: { label: "Corridors — monthly capacity", field: "monthly_capacity", flatField: "capacity", nameKey: "name" },
};

async function renderPlanningSection() {
  const panel = document.getElementById('planningPanel');
  const sub = document.querySelector('#planningTabs .tab.active').dataset.panel;
  if (sub === 'import') return renderExcelImportPanel(panel);
  if (sub === 'grid') return renderMonthlyGridPanel(panel);
  if (sub === 'results') return renderMonthlyResultsPanel(panel);
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('#planningTabs .tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('#planningTabs .tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      renderPlanningSection();
    });
  });
});

// ------------------------------------------------------------ Excel import --
function renderExcelImportPanel(panel) {
  panel.innerHTML = `
    <div class="card" style="max-width:800px;">
      <div class="card-title">Step 1 — Download</div>
      <p class="text-muted" style="font-size:12.5px;margin-top:-4px;">
        The blank template has every sheet's headers with no data. The sample dataset is a small,
        internally-consistent illustrative network (with 12 months of supply/demand data) that
        always passes validation — useful to see the exact expected format, or as a starting point.
      </p>
      <div style="display:flex;gap:8px;">
        <a class="btn" href="/api/data/${PROJECT_ID}/template">Download Blank Template</a>
        <a class="btn" href="/api/data/${PROJECT_ID}/sample">Download Sample Data</a>
      </div>
    </div>

    <div class="card" style="max-width:800px;margin-top:16px;">
      <div class="card-title">Step 2–4 — Upload, Validate, Preview</div>
      <div class="field"><input type="file" id="excelFile" accept=".xlsx,.xlsm"></div>
      <div style="display:flex;gap:8px;">
        <button class="btn primary" id="validateExcelBtn">Validate Workbook</button>
        <button class="btn" id="importExcelBtn" disabled>Step 5 — Import Dataset</button>
      </div>
      <div id="excelValidationResult" style="margin-top:16px;"></div>
    </div>
  `;

  let lastFileOk = false;

  document.getElementById('validateExcelBtn').addEventListener('click', async () => {
    const fileInput = document.getElementById('excelFile');
    if (!fileInput.files.length) { toast('Choose a file first', 'error'); return; }
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    try {
      const res = await fetch(`/api/data/${PROJECT_ID}/validate`, { method: 'POST', body: fd });
      const preview = await res.json();
      if (!res.ok) throw new Error(preview.error || 'Validation failed');
      lastFileOk = preview.status === 'PASSED';
      document.getElementById('importExcelBtn').disabled = !lastFileOk;
      renderExcelPreview(preview);
    } catch (e) { toast(e.message, 'error'); }
  });

  document.getElementById('importExcelBtn').addEventListener('click', async () => {
    const fileInput = document.getElementById('excelFile');
    if (!fileInput.files.length || !lastFileOk) return;
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    fd.append('mode', 'replace');
    try {
      const res = await fetch(`/api/data/${PROJECT_ID}/import`, { method: 'POST', body: fd });
      const result = await res.json();
      if (!res.ok) throw new Error(result.error || 'Import failed');
      toast(`Imported — dataset status: ${result.status}`, 'ok');
      currentProject = null;
      loadEntityTab('sources');
    } catch (e) { toast(e.message, 'error'); }
  });
}

function renderExcelPreview(preview) {
  const el = document.getElementById('excelValidationResult');
  const rows = Object.entries(preview.summary || {}).map(([k, v]) => `
    <tr><td>${k}</td><td>${v.added ?? v.records ?? ''}</td><td>${v.updated ?? ''}</td><td>${v.total_rows ?? ''}</td></tr>
  `).join('');
  const issueRows = (issues) => issues.map(i => `
    <tr>
      <td>${i.sheet || ''}</td><td>${i.row ?? ''}</td><td>${i.column || ''}</td>
      <td><span class="badge ${i.level === 'error' ? 'critical' : 'warn'}">${i.level}</span></td>
      <td>${i.message}</td>
    </tr>
  `).join('');

  el.innerHTML = `
    <div class="toolbar">
      <strong>Excel Validation Results</strong>
      <span class="badge ${preview.status === 'PASSED' ? 'ok' : 'critical'}">${preview.status}</span>
    </div>
    <p class="text-muted" style="font-size:12.5px;">
      Errors: <b>${preview.error_count}</b> &nbsp; Warnings: <b>${preview.warning_count}</b> &nbsp;
      Data quality: <b>${Math.round(preview.data_quality * 100)}%</b> &nbsp;
      Planning horizon: <b>${preview.planning_horizon_months} months</b>
    </p>
    ${rows ? `<table class="data-table"><thead><tr><th>Sheet</th><th>Added</th><th>Updated</th><th>Rows</th></tr></thead><tbody>${rows}</tbody></table>` : ''}
    ${(preview.errors.length || preview.warnings.length) ? `
      <table class="data-table" style="margin-top:10px;">
        <thead><tr><th>Sheet</th><th>Row</th><th>Column</th><th>Severity</th><th>Message</th></tr></thead>
        <tbody>${issueRows(preview.errors)}${issueRows(preview.warnings)}</tbody>
      </table>
    ` : '<p style="color:var(--ok);font-size:12.5px;">No issues found.</p>'}
  `;
}

// --------------------------------------------------------- monthly grid ----
async function renderMonthlyGridPanel(panel) {
  panel.innerHTML = `
    <div class="card">
      <div class="toolbar">
        <strong>Monthly Planning Data</strong>
        <select id="gridEntitySelect">
          <option value="sources">Sources</option>
          <option value="demand">Demand Zones</option>
          <option value="corridors">Corridors</option>
        </select>
      </div>
      <p class="text-muted" style="font-size:12px;">
        Leave a month blank to fall back to the flat master-data value shown in parentheses. Edits save
        on blur and feed directly into the 12-Month Optimization — this is the same data the Excel
        Monthly_Supply/Monthly_Demand/Monthly_Capacity sheets import into.
      </p>
      <div id="gridTableWrap" style="overflow-x:auto;"></div>
    </div>
  `;
  const select = document.getElementById('gridEntitySelect');
  select.addEventListener('change', () => loadGrid(select.value));
  loadGrid('sources');
}

async function loadGrid(entityKey) {
  const cfg = PLANNING_GRIDS[entityKey];
  const items = await api.get(`/api/network/${PROJECT_ID}/${entityKey}`);
  const wrap = document.getElementById('gridTableWrap');
  const monthHeaders = MONTH_NAMES.map(n => `<th style="min-width:70px;">${n}</th>`).join('');
  const rows = items.map(item => {
    const monthly = item[cfg.field] || {};
    const flat = item[cfg.flatField];
    const cells = MONTHS.map(m => `
      <td><input type="number" step="any" data-id="${item.id}" data-month="${m}"
                 value="${monthly[m] ?? monthly[String(m)] ?? ''}" placeholder="${flat ?? 0}"
                 style="width:70px;padding:4px;font-size:11.5px;"></td>
    `).join('');
    return `<tr><td class="mono" style="white-space:nowrap;">${item.code} <span class="text-muted">(${item[cfg.nameKey] || ''})</span></td>${cells}</tr>`;
  }).join('');

  wrap.innerHTML = items.length ? `
    <table class="data-table"><thead><tr><th>${cfg.label}</th>${monthHeaders}</tr></thead><tbody>${rows}</tbody></table>
  ` : `<p class="text-muted">No ${entityKey} configured yet — add some on the Network tab first.</p>`;

  wrap.querySelectorAll('input[data-id]').forEach(input => {
    input.addEventListener('blur', () => saveGridCell(entityKey, cfg, input));
  });
}

async function saveGridCell(entityKey, cfg, input) {
  const id = input.dataset.id;
  const month = input.dataset.month;
  try {
    const items = await api.get(`/api/network/${PROJECT_ID}/${entityKey}`);
    const item = items.find(i => String(i.id) === String(id));
    const monthly = { ...(item[cfg.field] || {}) };
    if (input.value === '') {
      delete monthly[month];
    } else {
      monthly[month] = parseFloat(input.value);
    }
    await api.patch(`/api/network/${PROJECT_ID}/${entityKey}/${id}`, { [cfg.field]: monthly });
    toast('Saved', 'ok');
  } catch (e) { toast(e.message, 'error'); }
}

// ------------------------------------------------------- monthly results ---
async function renderMonthlyResultsPanel(panel) {
  panel.innerHTML = `
    <div class="card">
      <div class="toolbar">
        <strong>12-Month Optimization</strong>
        <select id="allocationPolicy" style="margin-left:auto;">
          <option value="weighted">Mode A — Weighted penalty (priority_class weight)</option>
          <option value="lexicographic">Mode B — Lexicographic (fully protect each tier in rank order)</option>
        </select>
        <button class="btn primary" id="runMultiperiodBtn">Run 12-Month Optimization</button>
      </div>
      <p class="text-muted" style="font-size:12.5px;">
        A single time-indexed MILP over the whole horizon — not 12 independent solves — using
        whatever monthly data is set (missing months fall back to each entity's flat value).
        Lexicographic mode solves once per priority tier in rank order, each stage locking in
        the previous tier's shortage before the next tier is optimized — see the stage
        breakdown below the results.
      </p>
      <div id="multiperiodResult" class="mono text-muted" style="font-size:12px;">Not yet run.</div>
    </div>
  `;
  document.getElementById('runMultiperiodBtn').addEventListener('click', runMultiperiod);
}

async function runMultiperiod() {
  const el = document.getElementById('multiperiodResult');
  const policy = document.getElementById('allocationPolicy').value;
  const endpoint = policy === 'lexicographic'
    ? `/api/optimize/${PROJECT_ID}/multiperiod/lexicographic`
    : `/api/optimize/${PROJECT_ID}/multiperiod`;
  el.textContent = 'Solving...';
  try {
    const res = await api.post(endpoint, {});
    if (res.status !== 'optimal') {
      el.innerHTML = `<span style="color:var(--critical);">Status: ${res.status}</span>` +
        (res.diagnostics ? `<pre style="white-space:pre-wrap;">${JSON.stringify(res.diagnostics, null, 2)}</pre>` : '');
      return;
    }
    const balanceRows = res.monthly_breakdown.map(r => `
      <tr>
        <td>${MONTH_NAMES[r.month - 1]}</td><td>${r.supply_available}</td><td>${r.demand}</td>
        <td>${r.allocated}</td><td>${r.shortage}</td>
        <td>${r.surplus_deficit}</td><td>${(r.service_level * 100).toFixed(1)}%</td>
        <td>${r.cost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
      </tr>
    `).join('');

    // Node x Month allocation table
    const nodes = [...new Set(res.monthly_allocation.map(r => r.node))];
    const byNode = {};
    res.monthly_allocation.forEach(r => { (byNode[r.node] = byNode[r.node] || {})[r.month] = r; });
    const nodeRows = nodes.map(n => {
      const cells = MONTHS.map(m => {
        const r = byNode[n][m];
        const bad = r && r.shortage > 1e-6;
        return `<td style="${bad ? 'color:var(--critical);font-weight:600;' : ''}">${r ? r.allocated : '-'}</td>`;
      }).join('');
      return `<tr><td class="mono">${n}</td>${cells}</tr>`;
    }).join('');

    const stageBlock = res.lexicographic_stages ? `
      <div style="overflow-x:auto;margin-top:16px;">
        <div style="font-weight:600;font-size:12.5px;margin-bottom:6px;">Lexicographic Stage Breakdown</div>
        <table class="data-table">
          <thead><tr><th>Order</th><th>Tier</th><th>Zones</th><th>Total Shortage (horizon)</th></tr></thead>
          <tbody>${res.lexicographic_stages.map((s, i) => `
            <tr><td>${i + 1}</td><td>${s.tier}</td><td>${s.zones.join(', ')}</td><td>${s.total_shortage}</td></tr>
          `).join('')}</tbody>
        </table>
      </div>
    ` : '';

    el.innerHTML = `
      <div style="color:var(--ok);font-size:13px;margin-bottom:10px;">
        Optimal — total cost ${res.objective_value.toLocaleString()} · overall service level
        ${(res.kpis.overall_service_level * 100).toFixed(1)}% · ${res.kpis.months_with_shortage}/12 months with shortage
        ${res.policy === 'lexicographic' ? ' · policy: lexicographic (Mode B)' : ''}
      </div>
      ${stageBlock}
      <div style="overflow-x:auto;">
        <table class="data-table">
          <thead><tr><th>Month</th><th>Supply</th><th>Demand</th><th>Allocated</th><th>Shortage</th><th>Surplus/Deficit</th><th>Service %</th><th>Cost</th></tr></thead>
          <tbody>${balanceRows}</tbody>
        </table>
      </div>
      <div style="overflow-x:auto;margin-top:16px;">
        <div style="font-weight:600;font-size:12.5px;margin-bottom:6px;">Monthly Allocation by Node</div>
        <table class="data-table">
          <thead><tr><th>Node</th>${MONTH_NAMES.map(n => `<th>${n}</th>`).join('')}</tr></thead>
          <tbody>${nodeRows}</tbody>
        </table>
      </div>
    `;
  } catch (e) {
    el.innerHTML = `<span style="color:var(--critical);">${e.message}</span>`;
  }
}
