// Renders the CRUD table + add-form for one entity type inside a given
// container. Everything is driven by ENTITY_CONFIG - there is no
// per-entity-count assumption anywhere in here.

function fieldInputHTML(f, value) {
  const v = value === undefined || value === null ? (f.default ?? "") : value;
  if (f.type === "select") {
    const opts = f.options.map(o => `<option value="${o}" ${o === v ? "selected" : ""}>${o}</option>`).join("");
    return `<select name="${f.key}">${opts}</select>`;
  }
  if (f.type === "checkbox") {
    return `<input type="checkbox" name="${f.key}" ${v ? "checked" : ""} style="width:auto;">`;
  }
  const step = f.step ? `step="${f.step}"` : "";
  const placeholder = f.placeholder || f.label;
  return `<input type="${f.type}" name="${f.key}" value="${v}" ${step} placeholder="${placeholder}">`;
}

function readFormValues(formEl, fields) {
  const data = {};
  for (const f of fields) {
    const el = formEl.querySelector(`[name="${f.key}"]`);
    if (!el) continue;
    if (f.type === "checkbox") data[f.key] = el.checked;
    else if (f.type === "number") data[f.key] = el.value === "" ? null : parseFloat(el.value);
    else data[f.key] = el.value;
  }
  return data;
}

async function renderEntitySection(containerEl, projectId, entityKey) {
  const cfg = ENTITY_CONFIG[entityKey];
  containerEl.innerHTML = `
    <div class="toolbar">
      <div>
        <strong>${cfg.icon} ${cfg.label}</strong>
        <span class="text-muted" id="${entityKey}-count" style="margin-left:8px;font-family:var(--font-mono);font-size:12.5px;"></span>
      </div>
      <button class="btn primary small" id="${entityKey}-add-toggle">+ Add ${cfg.label.replace(/s$/, "")}</button>
    </div>
    ${cfg.hint ? `<p class="text-muted" style="font-size:12.5px;margin:-6px 0 16px 0;">${cfg.hint}</p>` : ""}
    <div id="${entityKey}-form-wrap" style="display:none;margin-bottom:16px;"></div>
    <div style="overflow-x:auto;">
      <table class="data-table"><thead><tr>
        ${cfg.tableCols.map(c => `<th>${(cfg.fields.find(f => f.key === c) || { label: c }).label}</th>`).join("")}
        <th></th>
      </tr></thead><tbody id="${entityKey}-tbody"></tbody></table>
    </div>
    <div id="${entityKey}-empty" class="empty-state" style="display:none;">
      <div class="icon">${cfg.icon}</div>No ${cfg.label.toLowerCase()} defined yet.
    </div>
  `;

  const formWrap = containerEl.querySelector(`#${entityKey}-form-wrap`);
  const toggleBtn = containerEl.querySelector(`#${entityKey}-add-toggle`);

  function buildForm(existing) {
    const fieldsHTML = cfg.fields.map(f => `
      <div class="field" style="min-width:160px;">
        <label>${f.label}${f.required ? " *" : ""}</label>
        ${fieldInputHTML(f, existing ? existing[f.key] : undefined)}
      </div>
    `).join("");
    return `
      <div class="card" style="background:var(--surface);">
        <form id="${entityKey}-form" style="display:flex;flex-wrap:wrap;gap:12px;align-items:end;">
          ${fieldsHTML}
          <div class="field" style="min-width:auto;">
            <button type="submit" class="btn primary small">${existing ? "Save" : "Add"}</button>
            <button type="button" class="btn ghost small" id="${entityKey}-cancel">Cancel</button>
          </div>
        </form>
      </div>
    `;
  }

  toggleBtn.addEventListener("click", () => {
    formWrap.innerHTML = buildForm(null);
    formWrap.style.display = "block";
    wireForm(null);
  });

  function wireForm(existingItem) {
    const form = formWrap.querySelector("form");
    formWrap.querySelector(`#${entityKey}-cancel`).addEventListener("click", () => {
      formWrap.style.display = "none";
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = readFormValues(form, cfg.fields);
      for (const f of cfg.fields) {
        if (f.required && (data[f.key] === "" || data[f.key] === null || data[f.key] === undefined)) {
          toast(`${f.label} is required`, "error");
          return;
        }
      }
      try {
        if (existingItem) {
          await api.patch(`/api/network/${projectId}/${entityKey}/${existingItem.id}`, data);
          toast("Saved", "ok");
        } else {
          await api.post(`/api/network/${projectId}/${entityKey}`, data);
          toast("Added", "ok");
        }
        formWrap.style.display = "none";
        await loadTable();
        if (window.onNetworkChanged) window.onNetworkChanged();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  async function loadTable() {
    const items = await api.get(`/api/network/${projectId}/${entityKey}`);
    const tbody = containerEl.querySelector(`#${entityKey}-tbody`);
    tbody.innerHTML = "";
    containerEl.querySelector(`#${entityKey}-count`).textContent = `${items.length} defined`;
    containerEl.querySelector(`#${entityKey}-empty`).style.display = items.length ? "none" : "block";
    for (const item of items) {
      const tr = document.createElement("tr");
      tr.innerHTML = cfg.tableCols.map(c => {
        const f = cfg.fields.find(x => x.key === c);
        let val = item[c];
        if (f && f.type === "checkbox") val = val ? "yes" : "no";
        if (val === null || val === undefined) val = "—";
        const cls = (f && f.type === "text" || f && f.type === "select") ? "text-cell" : "";
        return `<td class="${cls}">${val}</td>`;
      }).join("") + `<td>
          <button class="btn ghost small edit-btn">edit</button>
          <button class="btn ghost small danger del-btn">delete</button>
        </td>`;
      tr.querySelector(".edit-btn").addEventListener("click", () => {
        formWrap.innerHTML = buildForm(item);
        formWrap.style.display = "block";
        wireForm(item);
      });
      tr.querySelector(".del-btn").addEventListener("click", async () => {
        if (!confirm(`Delete ${item.code || item.name}?`)) return;
        try {
          await api.delete(`/api/network/${projectId}/${entityKey}/${item.id}`);
          toast("Deleted", "ok");
          await loadTable();
          if (window.onNetworkChanged) window.onNetworkChanged();
        } catch (err) { toast(err.message, "error"); }
      });
      tbody.appendChild(tr);
    }
  }

  await loadTable();
  return loadTable;
}
