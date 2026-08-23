const api = {
  async _fetch(path, opts) {
    const res = await fetch(path, opts);
    let body = null;
    try { body = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      const msg = (body && body.error) ? body.error : `Request failed (${res.status})`;
      throw new Error(msg);
    }
    return body;
  },
  get(path) {
    return this._fetch(path);
  },
  post(path, data) {
    return this._fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    });
  },
  patch(path, data) {
    return this._fetch(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    });
  },
  delete(path) {
    return this._fetch(path, { method: "DELETE" });
  },
};

function toast(message, kind = "info") {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:999;max-width:360px;";
    document.body.appendChild(el);
  }
  const item = document.createElement("div");
  const colors = { info: "#33b1c9", error: "#e0574c", ok: "#3fbf7f" };
  item.style.cssText = `background:#16233a;border:1px solid ${colors[kind] || colors.info};
    color:#e7edf5;padding:10px 14px;border-radius:4px;margin-top:8px;font-size:12.5px;
    font-family:'IBM Plex Mono',monospace;box-shadow:0 4px 14px rgba(0,0,0,0.4);`;
  item.textContent = message;
  el.appendChild(item);
  setTimeout(() => item.remove(), 4500);
}
