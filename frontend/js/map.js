const london = [51.5074, -0.1278];

const map = L.map("map").setView(london, 10);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

L.marker(london).addTo(map).bindPopup("Trial marker — wire to your API / GeoJSON.");
