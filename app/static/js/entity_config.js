// Field configuration for each dynamic network entity.
// This is the single source of truth the network builder UI reads to
// generate table columns and add/edit forms - adding a field here is
// the only change needed to expose it in the UI.
//
// Every field carries a `placeholder` with 2-3 realistic sample values,
// so someone unfamiliar with the domain has a concrete sense of scale
// and format before typing anything.

const ENTITY_CONFIG = {
  sources: {
    label: "Sources", icon: "◈",
    hint: "A source is anywhere gas enters your network - a domestic gas field, an LNG import terminal, etc.",
    fields: [
      { key: "code", label: "Source ID", type: "text", required: true, placeholder: "e.g. SRC-01, SRC-02, SRC-03" },
      { key: "name", label: "Name", type: "text", required: true, placeholder: "e.g. Domestic Field A, LNG Terminal North" },
      { key: "source_type", label: "Type", type: "select", options: ["Domestic", "LNG Terminal", "Other"] },
      { key: "latitude", label: "Latitude", type: "number", step: "any", placeholder: "e.g. 23.75, 22.30, 19.08" },
      { key: "longitude", label: "Longitude", type: "number", step: "any", placeholder: "e.g. 68.85, 69.10, 72.88" },
      { key: "max_capacity", label: "Max capacity", type: "number", placeholder: "e.g. 300, 500, 800" },
      { key: "base_availability", label: "Base availability (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.85, 0.95, 1.0" },
      { key: "min_operational_qty", label: "Min operational qty", type: "number", placeholder: "e.g. 20, 50, 100" },
      { key: "supply_cost", label: "Supply cost / unit", type: "number", step: "0.01", placeholder: "e.g. 4.5, 6.0, 8.5" },
      { key: "contracted_quantity", label: "Contracted qty", type: "number", placeholder: "e.g. 250, 400, 700" },
      { key: "reliability", label: "Reliability (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.85, 0.90, 0.98" },
      { key: "infra_status", label: "Status", type: "select", options: ["existing", "candidate"] },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
    tableCols: ["code", "name", "source_type", "max_capacity", "base_availability", "supply_cost", "reliability", "infra_status", "is_active"],
  },
  corridors: {
    label: "Corridors / Pipelines", icon: "→",
    hint: "A corridor connects a source to a City Gate Station - typically a physical pipeline.",
    fields: [
      { key: "code", label: "Corridor ID", type: "text", required: true, placeholder: "e.g. COR-01, COR-02, COR-03" },
      { key: "name", label: "Name", type: "text", required: true, placeholder: "e.g. Domestic to North CGS" },
      { key: "origin_type", label: "Origin type", type: "select", options: ["source", "cgs"] },
      { key: "origin_code", label: "Origin ID", type: "text", required: true, placeholder: "e.g. SRC-01 (must match an existing Source ID)" },
      { key: "destination_type", label: "Destination type", type: "select", options: ["cgs", "station"] },
      { key: "destination_code", label: "Destination ID", type: "text", required: true, placeholder: "e.g. CGS-01 (must match an existing CGS ID)" },
      { key: "capacity", label: "Capacity", type: "number", placeholder: "e.g. 200, 400, 600" },
      { key: "distance_km", label: "Distance (km)", type: "number", placeholder: "e.g. 50, 150, 400" },
      { key: "transport_cost", label: "Transport cost / unit", type: "number", step: "0.01", placeholder: "e.g. 0.8, 1.5, 2.5" },
      { key: "fixed_cost", label: "Fixed cost", type: "number", placeholder: "e.g. 0, 10, 25" },
      { key: "loss_pct", label: "Loss (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.01, 0.02, 0.05" },
      { key: "reliability", label: "Reliability (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.85, 0.92, 0.98" },
      { key: "pipeline_type", label: "Mode", type: "select", options: ["pipeline", "virtual"] },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
    tableCols: ["code", "name", "origin_code", "destination_code", "capacity", "distance_km", "transport_cost", "pipeline_type", "is_active"],
  },
  cgs: {
    label: "City Gate Stations (CGS)", icon: "▣",
    hint: "A City Gate Station receives gas from sources and distributes it onward to CNG retail stations.",
    fields: [
      { key: "code", label: "CGS ID", type: "text", required: true, placeholder: "e.g. CGS-01, CGS-02, CGS-03" },
      { key: "name", label: "Name", type: "text", required: true, placeholder: "e.g. City Gate North, City Gate West" },
      { key: "latitude", label: "Latitude", type: "number", step: "any", placeholder: "e.g. 28.60, 19.08, 21.15" },
      { key: "longitude", label: "Longitude", type: "number", step: "any", placeholder: "e.g. 77.20, 72.88, 79.09" },
      { key: "capacity", label: "Capacity", type: "number", placeholder: "e.g. 300, 600, 900" },
      { key: "fixed_operating_cost", label: "Fixed operating cost", type: "number", placeholder: "e.g. 80, 150, 220" },
      { key: "expansion_cost", label: "Expansion cost / unit", type: "number", step: "0.01", placeholder: "e.g. 0.3, 0.45, 0.6" },
      { key: "max_expansion", label: "Max expansion", type: "number", placeholder: "e.g. 100, 200, 350" },
      { key: "infra_status", label: "Status", type: "select", options: ["existing", "candidate"] },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
    tableCols: ["code", "name", "capacity", "fixed_operating_cost", "expansion_cost", "infra_status", "is_active"],
  },
  stations: {
    label: "CNG Retail Stations", icon: "⛽",
    hint: "The pumps where vehicles actually fill up. Each station gets its gas from a nearby CGS.",
    fields: [
      { key: "code", label: "Station ID", type: "text", required: true, placeholder: "e.g. STN-01, STN-02, STN-03" },
      { key: "name", label: "Name", type: "text", required: true, placeholder: "e.g. Station North-1, Station Central" },
      { key: "latitude", label: "Latitude", type: "number", step: "any", placeholder: "e.g. 28.61, 19.07, 21.16" },
      { key: "longitude", label: "Longitude", type: "number", step: "any", placeholder: "e.g. 77.21, 72.87, 79.10" },
      { key: "capacity", label: "Capacity", type: "number", placeholder: "e.g. 100, 200, 300" },
      { key: "fixed_cost", label: "Fixed cost", type: "number", placeholder: "e.g. 15, 30, 45" },
      { key: "expansion_cost", label: "Expansion cost / unit", type: "number", step: "0.01", placeholder: "e.g. 0.2, 0.3, 0.4" },
      { key: "infra_status", label: "Status", type: "select", options: ["existing", "candidate"] },
      { key: "demand_service_radius_km", label: "Service radius (km)", type: "number", placeholder: "e.g. 20, 35, 50" },
      { key: "is_active", label: "Active", type: "checkbox", default: true },
    ],
    tableCols: ["code", "name", "capacity", "fixed_cost", "infra_status", "demand_service_radius_km", "is_active"],
  },
  demand: {
    label: "Demand Zones", icon: "◉",
    hint: "A demand zone is a city, district, or area whose gas requirement you want the model to satisfy.",
    fields: [
      { key: "code", label: "Zone ID", type: "text", required: true, placeholder: "e.g. DZ-01, DZ-02, DZ-03" },
      { key: "name", label: "Name", type: "text", required: true, placeholder: "e.g. Delhi, Gurugram, Nagpur" },
      { key: "latitude", label: "Latitude", type: "number", step: "any", placeholder: "e.g. 28.61, 19.08, 21.15" },
      { key: "longitude", label: "Longitude", type: "number", step: "any", placeholder: "e.g. 77.21, 72.88, 79.09" },
      { key: "base_demand", label: "Base demand", type: "number", placeholder: "e.g. 80, 150, 220" },
      { key: "growth_rate", label: "Growth rate / yr (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.03, 0.05, 0.08" },
      { key: "demand_type", label: "Demand type", type: "select", options: ["Transport", "Industrial", "Commercial", "Domestic", "Private Vehicles", "Mixed"] },
      { key: "min_service_level", label: "Min service level (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.6, 0.8, 0.95" },
      { key: "max_service_level", label: "Max service level (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.9, 1.0" },
    ],
    tableCols: ["code", "name", "base_demand", "growth_rate", "demand_type", "min_service_level"],
  },
  priorities: {
    label: "Priority Classes", icon: "◆",
    hint: "Ranks who gets served first if there isn't enough gas to go around - e.g. hospitals before private cars.",
    fields: [
      { key: "name", label: "Class name", type: "text", required: true, placeholder: "e.g. Public Transport, Industrial, Private Vehicles" },
      { key: "rank", label: "Rank (1=highest)", type: "number", placeholder: "e.g. 1, 2, 3" },
      { key: "min_fulfilment_pct", label: "Min fulfilment (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.6, 0.8, 0.95" },
      { key: "max_fulfilment_pct", label: "Max fulfilment (0-1)", type: "number", step: "0.01", placeholder: "e.g. 0.9, 1.0" },
      { key: "penalty_weight", label: "Penalty weight", type: "number", step: "0.1", placeholder: "e.g. 1.0, 2.5, 5.0" },
    ],
    tableCols: ["name", "rank", "min_fulfilment_pct", "max_fulfilment_pct", "penalty_weight"],
  },
};
