const NODE_STYLE = {
  source:  { color: "#33b1c9", radius: 8, label: "Source / LNG Terminal" },
  cgs:     { color: "#e3a63c", radius: 7, label: "City Gate Station" },
  station: { color: "#3fbf7f", radius: 6, label: "CNG Station" },
  demand:  { color: "#8f8fe0", radius: 6, label: "Demand Zone" },
};

let networkMap = null;
let networkLayerGroup = null;

function initNetworkMap(elId) {
  networkMap = L.map(elId, { zoomControl: true }).setView([22.5, 78.9], 5);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd", maxZoom: 19,
  }).addTo(networkMap);
  networkLayerGroup = L.layerGroup().addTo(networkMap);
  return networkMap;
}

async function refreshNetworkMap(projectId) {
  if (!networkMap) return;
  networkLayerGroup.clearLayers();
  const graph = await api.get(`/api/network/${projectId}/graph`);
  const coords = {};

  for (const n of graph.nodes) {
    if (n.lat == null || n.lng == null) continue;
    coords[n.id] = [n.lat, n.lng];
  }

  // edges first (so nodes draw on top)
  for (const e of graph.edges) {
    const a = coords[e.source], b = coords[e.target];
    if (!a || !b) continue;
    const isService = e.type === "service";
    L.polyline([a, b], {
      color: isService ? "#3fbf7f" : (e.type === "virtual" ? "#e3a63c" : "#33b1c9"),
      weight: isService ? 1 : 2,
      opacity: e.active === false ? 0.15 : (isService ? 0.35 : 0.6),
      dashArray: isService ? "2,5" : (e.type === "virtual" ? "6,4" : null),
    }).addTo(networkLayerGroup);
  }

  for (const n of graph.nodes) {
    if (n.lat == null || n.lng == null) continue;
    const style = NODE_STYLE[n.type] || { color: "#999", radius: 6 };
    const marker = L.circleMarker([n.lat, n.lng], {
      radius: style.radius,
      color: n.active === false ? "#5d7188" : style.color,
      fillColor: n.active === false ? "#5d7188" : style.color,
      fillOpacity: 0.85,
      weight: n.infra_status === "candidate" ? 1 : 2,
      dashArray: n.infra_status === "candidate" ? "3,3" : null,
    }).addTo(networkLayerGroup);

    const statusLabel = n.active === false ? "Inactive" : (n.infra_status === "candidate" ? "Candidate" : "Existing");
    marker.bindPopup(`
      <div class="mono" style="font-size:12px;min-width:180px;">
        <div style="font-weight:600;font-size:13px;margin-bottom:4px;">${n.id} — ${n.name}</div>
        <div style="color:#8fa2b8;text-transform:uppercase;font-size:10px;letter-spacing:.05em;margin-bottom:6px;">${style.label || n.type}</div>
        <div>Capacity: ${n.capacity ?? "—"}</div>
        <div>Status: ${statusLabel}</div>
      </div>
    `);
  }

  if (graph.nodes.some(n => n.lat != null)) {
    const bounds = graph.nodes.filter(n => n.lat != null).map(n => [n.lat, n.lng]);
    if (bounds.length) networkMap.fitBounds(bounds, { padding: [30, 30], maxZoom: 8 });
  }
}
