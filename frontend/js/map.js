const london = [51.5074, -0.1278];

const map = L.map("map").setView(london, 10);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/** Column order matches combined `master_all` row keys (0-based indices). */
const TOOLTIP_BY_COL_INDEX = [
  { i: 1, label: "Source" },
  { i: 5, label: "Address" },
  { i: 11, label: "Sub-sector" },
  { i: 15, label: "Floor area" },
  { i: 21, label: "No. of key tenants" },
];

function tooltipHtmlFromColumnOrder(props) {
  const keys = Object.keys(props ?? {});
  const parts = [];
  for (const { i, label } of TOOLTIP_BY_COL_INDEX) {
    const k = keys[i];
    if (!k) continue;
    const v = props[k];
    if (v == null || String(v).trim() === "") continue;
    parts.push(
      `<div class="newmark-tip-row"><span class="newmark-tip-label">${escapeHtml(label)}</span> ${escapeHtml(String(v))}</div>`
    );
  }
  return parts.length ? parts.join("") : `<span class="muted">No details</span>`;
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
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, { radius: 6, weight: 1, fillOpacity: 0.9 }),
      onEachFeature: (feature, l) => {
        const props = feature?.properties ?? {};
        l.bindPopup(popupHtml(props));
        l.bindTooltip(tooltipHtmlFromColumnOrder(props), {
          sticky: true,
          direction: "top",
          opacity: 0.95,
          className: "newmark-map-tip",
          interactive: true,
        });
      },
    }).addTo(map);
    try {
      map.fitBounds(layer.getBounds(), { padding: [20, 20] });
    } catch {
      // ignore empty bounds
    }
  })
  .catch((err) => {
    L.marker(london).addTo(map).bindPopup(`Could not load Newmark points: ${escapeHtml(err.message)}`);
  });
