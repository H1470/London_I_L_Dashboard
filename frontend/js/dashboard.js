/**
 * Dashboard section: KPIs from ``/api/summary`` and market tables from ``/api/indices``
 * (Chatham + yfinance rows rendered into ``#chatham-rows`` / ``#yf-ticker-rows``).
 */
import { fetchIndices, fetchSummary } from "./api.js";

function fmtKpi(value, unit) {
  if (unit === "GBP") return `£${Number(value).toLocaleString("en-GB")}`;
  if (unit === "%") return `${value}%`;
  return Number(value).toLocaleString("en-GB");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderPercentTableRows(tbodyId, rows) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;

  if (!rows || rows.length === 0) {
    tbody.innerHTML = "";
    return;
  }

  tbody.innerHTML = rows
    .map((row) => {
      if (row.error) {
        return `<tr><td>${escapeHtml(row.label)}</td><td colspan="4">${escapeHtml(row.error)}</td></tr>`;
      }
      const d = Number(row.decimals) >= 0 ? Number(row.decimals) : 2;
      const today = Number(row.price).toFixed(d);
      const prev = Number(row.previousClose).toFixed(d);
      const band = `${Number(row.fiftyTwoWeekLow).toFixed(d)} - ${Number(row.fiftyTwoWeekHigh).toFixed(d)}`;
      const changeNum = parseFloat(String(row.change).replace(/[^0-9.-]/g, ""));
      const color = changeNum >= 0 ? "#437a22" : "#a13544";
      const changeCell = `<td style="color:${color};font-weight:bold">${escapeHtml(row.change)} (${escapeHtml(row.changePercent)}%)</td>`;
      return `<tr><td>${escapeHtml(row.label)}</td><td>${today}</td><td>${prev}</td>${changeCell}<td>${band}</td></tr>`;
    })
    .join("");
}

function setTableLoading(tbodyId, message) {
  const tbody = document.getElementById(tbodyId);
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="5">${escapeHtml(message)}</td></tr>`;
  }
}

export async function loadDashboardData() {
  setTableLoading("chatham-rows", "Loading Chatham data…");
  setTableLoading("yf-ticker-rows", "Loading market data…");

  try {
    const data = await fetchIndices();

    const ftse100 = data.ftse100;
    document.getElementById("ftse100-today").textContent = ftse100.price.toFixed(2);
    document.getElementById("ftse100-previous").textContent = ftse100.previousClose.toFixed(2);

    const ftse100ChangeCell = document.getElementById("ftse100-change");
    const ftse100ChangeValue = parseFloat(String(ftse100.change).replace(/[^0-9.-]/g, ""));
    ftse100ChangeCell.textContent = `${ftse100.change} (${ftse100.changePercent}%)`;
    ftse100ChangeCell.style.color = ftse100ChangeValue >= 0 ? "#437a22" : "#a13544";
    ftse100ChangeCell.style.fontWeight = "bold";

    document.getElementById("ftse100-position").textContent = `${ftse100.fiftyTwoWeekLow.toFixed(2)} - ${ftse100.fiftyTwoWeekHigh.toFixed(2)}`;

    const ftse250 = data.ftse250;
    document.getElementById("ftse250-today").textContent = ftse250.price.toFixed(2);
    document.getElementById("ftse250-previous").textContent = ftse250.previousClose.toFixed(2);

    const ftse250ChangeCell = document.getElementById("ftse250-change");
    const ftse250ChangeValue = parseFloat(String(ftse250.change).replace(/[^0-9.-]/g, ""));
    ftse250ChangeCell.textContent = `${ftse250.change} (${ftse250.changePercent}%)`;
    ftse250ChangeCell.style.color = ftse250ChangeValue >= 0 ? "#437a22" : "#a13544";
    ftse250ChangeCell.style.fontWeight = "bold";

    document.getElementById("ftse250-position").textContent = `${ftse250.fiftyTwoWeekLow.toFixed(2)} - ${ftse250.fiftyTwoWeekHigh.toFixed(2)}`;

    renderPercentTableRows("chatham-rows", data.chatham_rows || []);
    renderPercentTableRows("yf-ticker-rows", data.yfinance_rows || []);
  } catch (error) {
    console.error("Error loading dashboard data:", error);
    document.getElementById("ftse100-today").textContent = "Error";
    document.getElementById("ftse250-today").textContent = "Error";
    setTableLoading("chatham-rows", error.message || String(error));
    setTableLoading("yf-ticker-rows", error.message || String(error));
  }
}

export async function loadTrialSummary() {
  const kpisEl = document.getElementById("trial-kpis");
  const rowsEl = document.getElementById("trial-rows");
  if (!kpisEl || !rowsEl) return;

  try {
    const data = await fetchSummary();
    kpisEl.innerHTML = (data.kpis || [])
      .map(
        (k) => `
        <div class="trial-kpi">
          <div class="label">${k.label}</div>
          <div class="value">${fmtKpi(k.value, k.unit)}</div>
        </div>`
      )
      .join("");

    rowsEl.innerHTML = (data.recent_rows || [])
      .map((r) => `<tr><td>${r.entity}</td><td>${r.region}</td><td>${r.score}</td></tr>`)
      .join("");
  } catch (e) {
    rowsEl.innerHTML = `<tr><td colspan="3">Could not load /api/summary (${String(e.message || e)})</td></tr>`;
  }
}
