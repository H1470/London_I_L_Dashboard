const london = [51.5074, -0.1278];

/** Fixed centre + zoom: reliable inside iframes (fitBounds on first paint often mis-zooms). */
const UK_CENTER = L.latLng(54.2, -3.5);
const UK_ZOOM = 5;

const map = L.map("map");
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

/**
 * Whole-UK view. Re-run after layout: iframe maps often report wrong size on first paint.
 */
function applyUkMapFrame() {
  map.invalidateSize();
  map.setView(UK_CENTER, UK_ZOOM, { animate: false });
}

function scheduleUkMapFrame() {
  applyUkMapFrame();
  requestAnimationFrame(() => {
    applyUkMapFrame();
    setTimeout(applyUkMapFrame, 50);
    setTimeout(applyUkMapFrame, 200);
    setTimeout(applyUkMapFrame, 600);
  });
}

map.whenReady(() => scheduleUkMapFrame());
window.addEventListener("resize", () => applyUkMapFrame());

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/**
 * Tooltip fields by 1-based column position in `master_all` property key order
 * (same order as GeoJSON `properties` / SQLite row columns).
 */
const TOOLTIP_BY_COL_1BASED = [
  { col: 1, label: "Source" },
  { col: 5, label: "Address" },
  { col: 11, label: "Sub-sector" },
  { col: 15, label: "Floor area" },
  { col: 21, label: "No. of key tenants" },
];

function tooltipTextFromColumnOrder(props) {
  const keys = Object.keys(props ?? {});
  const lines = [];
  for (const { col, label } of TOOLTIP_BY_COL_1BASED) {
    const i = col - 1;
    if (i < 0 || i >= keys.length) continue;
    const k = keys[i];
    const v = props[k];
    if (v == null || String(v).trim() === "") continue;
    const flat = String(v).replace(/\s+/g, " ").trim();
    lines.push(`${label}: ${flat}`);
  }
  return lines.length ? lines.join("\n") : "No details";
}

function popupHtml(props) {
  // Prefer a few common fields if present; otherwise show a compact key list.
  const keys = Object.keys(props ?? {}).filter((k) => props[k] != null && String(props[k]).trim() !== "");
  const preferred = [
    "Property",
    "Address",
    "Asset",
    "Name",
    "Postcode",
    "Town",
    "City",
    "Buyer",
    "Seller",
    "Price",
    "Date",
    "source",
  ];
  const show = [];
  for (const k of preferred) if (keys.includes(k)) show.push(k);
  if (show.length === 0) show.push(...keys.slice(0, 8));

  const rows = show
    .map((k) => `<div class="row"><strong>${escapeHtml(k)}</strong><div>${escapeHtml(props[k])}</div></div>`)
    .join("");
  return `<div style="min-width:240px;max-width:360px">${rows || "<em>No details</em>"}</div>`;
}

async function loadNewmarkPoints() {
  const res = await fetch("/api/newmark/geojson?limit=20000", { cache: "no-store" });
  if (!res.ok) throw new Error(`GeoJSON fetch failed: ${res.status}`);
  return await res.json();
}

loadNewmarkPoints()
  .then((geojson) => {
    const layer = L.geoJSON(geojson, {
      pointToLayer: (feature, latlng) =>
        L.circleMarker(latlng, { radius: 8, weight: 2, fillOpacity: 0.88, interactive: true }),
      onEachFeature: (feature, l) => {
        const props = feature?.properties ?? {};
        l.bindPopup(popupHtml(props));
        l.bindTooltip(tooltipTextFromColumnOrder(props), {
          sticky: true,
          direction: "auto",
          opacity: 1,
          className: "newmark-map-tip",
        });
      },
    }).addTo(map);
    scheduleUkMapFrame();
  })
  .catch((err) => {
    L.marker(london).addTo(map).bindPopup(`Could not load Newmark points: ${escapeHtml(err.message)}`);
    scheduleUkMapFrame();
  });
