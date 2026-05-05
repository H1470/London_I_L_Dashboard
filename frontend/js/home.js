import { fetchSummary } from "./api.js";

function fmt(n, unit) {
  if (unit === "GBP") return `£${n.toLocaleString("en-GB")}`;
  if (unit === "%") return `${n}%`;
  return n.toLocaleString("en-GB");
}

function render(data) {
  const kpis = document.getElementById("kpis");
  const rows = document.getElementById("rows");
  const err = document.getElementById("error");

  err.hidden = true;
  kpis.innerHTML = (data.kpis || [])
    .map(
      (k) => `
      <div class="kpi">
        <div class="label">${k.label}</div>
        <div class="value">${fmt(k.value, k.unit)}</div>
      </div>`
    )
    .join("");

  rows.innerHTML = (data.recent_rows || [])
    .map((r) => `<tr><td>${r.entity}</td><td>${r.region}</td><td>${r.score}</td></tr>`)
    .join("");
}

async function load(q) {
  try {
    const data = await fetchSummary(q || undefined);
    render(data);
    const input = document.getElementById("q");
    if (q !== undefined && input) input.value = q || "";
  } catch (e) {
    const err = document.getElementById("error");
    err.textContent = String(e.message || e);
    err.hidden = false;
  }
}

document.getElementById("search-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = document.getElementById("q").value.trim();
  load(q);
});

const params = new URLSearchParams(window.location.search);
load(params.get("q") || "");
