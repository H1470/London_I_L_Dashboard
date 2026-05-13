/**
 * Planning tab: when opened (see ``app.js`` ``showPage``), GET ``/api/planning/results``.
 * Backend calls Planning Datahub and persists CSV; this module only renders JSON into a table.
 */
function planningResultsUrl() {
  try {
    return new URL("/api/planning/results", window.location.origin).href;
  } catch {
    return "/api/planning/results";
  }
}

/**
 * Call when ``#planning`` gains ``.active`` so data loads even if navigation bypasses ``showPage``.
 */
export function initPlanningSectionLoader() {
  const section = document.getElementById("planning");
  if (!section) {
    console.warn("[planning] Missing #planning section");
    return;
  }

  const loadIfActive = () => {
    if (!section.classList.contains("active")) return;
    void refreshPlanningPage();
  };

  const obs = new MutationObserver(loadIfActive);
  obs.observe(section, { attributes: true, attributeFilter: ["class"] });
  loadIfActive();
}

export async function refreshPlanningPage() {
  const theadRow = document.getElementById("planning-thead-row");
  const tbody = document.getElementById("planning-tbody");
  const statusEl = document.getElementById("planning-load-status");

  if (!theadRow || !tbody) {
    const hint =
      "Planning table markup not found (#planning-thead-row / #planning-tbody). Serve this app from the FastAPI root (http://127.0.0.1:8000/) and hard-refresh (Ctrl+Shift+R).";
    console.error("[planning]", hint);
    if (statusEl) statusEl.textContent = hint;
    return;
  }

  theadRow.innerHTML = "";
  const loadingTh = document.createElement("th");
  loadingTh.className = "muted";
  loadingTh.scope = "col";
  loadingTh.textContent = "…";
  theadRow.appendChild(loadingTh);

  tbody.innerHTML = "";
  const loadingTr = document.createElement("tr");
  const loadingTd = document.createElement("td");
  loadingTd.className = "muted";
  loadingTd.textContent = "Loading…";
  loadingTr.appendChild(loadingTd);
  tbody.appendChild(loadingTr);

  if (statusEl) statusEl.textContent = "Loading planning data…";

  try {
    const res = await fetch(planningResultsUrl(), { method: "GET", cache: "no-store" });
    const rawText = await res.text();

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${rawText.slice(0, 400)}`);
    }

    let data;
    try {
      data = JSON.parse(rawText);
    } catch {
      throw new Error("Server did not return JSON.");
    }

    const columns = Array.isArray(data.columns) ? data.columns : [];
    const rows = Array.isArray(data.rows) ? data.rows : [];

    theadRow.innerHTML = "";

    if (columns.length === 0) {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = "Message";
      theadRow.appendChild(th);

      tbody.innerHTML = "";
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.className = "muted";
      td.textContent = data.message || "No columns in response.";
      tr.appendChild(td);
      tbody.appendChild(tr);

      if (statusEl) statusEl.textContent = data.message || "No columns.";
      return;
    }

    columns.forEach((col) => {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = col;
      theadRow.appendChild(th);
    });

    tbody.innerHTML = "";

    if (rows.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.className = "muted";
      td.colSpan = columns.length;
      td.textContent = `No rows (row_count=${data.row_count ?? 0}).`;
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      const frag = document.createDocumentFragment();
      rows.forEach((row) => {
        const tr = document.createElement("tr");
        columns.forEach((key) => {
          const td = document.createElement("td");
          const v = row != null ? row[key] : undefined;
          if (v === null || v === undefined || v === "") {
            const sp = document.createElement("span");
            sp.className = "muted";
            sp.textContent = "—";
            td.appendChild(sp);
          } else if (typeof v === "object") {
            td.textContent = JSON.stringify(v);
          } else {
            td.textContent = String(v);
          }
          tr.appendChild(td);
        });
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
    }

    const bits = [`${rows.length} row(s) in table.`];
    if (data.query_mode) bits.push(`Mode: ${data.query_mode}.`);
    if (data.live_fetch && data.decision_date_gt != null) {
      const statuses =
        Array.isArray(data.status_filter_labels) && data.status_filter_labels.length
          ? `any of: ${data.status_filter_labels.join(", ")}`
          : "configured statuses";
      bits.push(`Filters: status ${statuses}; decision_date > ${data.decision_date_gt}.`);
    }
    if (data.live_fetch && data.es_gia_existing_gt != null) {
      bits.push(
        `ES query: application_details GIA > ${data.es_gia_existing_gt} (floorspace gia_existing OR total_gia_existing).`
      );
    }
    if (
      data.es_hits_in_response != null &&
      data.upstream_stored_hits != null &&
      data.es_hits_in_response !== data.upstream_stored_hits
    ) {
      bits.push(
        `Store allowlist: ${data.upstream_stored_hits} of ${data.es_hits_in_response} hit(s) kept (use_class B8, B2, E(g)(iii)).`
      );
    }
    if (data.elasticsearch_total != null) bits.push(`ES total: ${data.elasticsearch_total}.`);
    if (
      data.pre_use_class_allowlist_row_count > 0 &&
      Array.isArray(data.store_use_class_allowlist)
    ) {
      bits.push(
        `Table use_class allowlist: ${rows.length} of ${data.pre_use_class_allowlist_row_count} parsed row(s) (${data.store_use_class_allowlist.join(", ")}).`
      );
    }
    if (data.client_filters_applied && data.pre_client_filter_row_count != null) {
      bits.push(
        `Filtered: ${data.row_count ?? 0} of ${data.pre_client_filter_row_count} row(s)${data.client_filters ? ` (${JSON.stringify(data.client_filters)})` : ""}.`
      );
    }
    if (data.planning_search_size != null) bits.push(`ES request size: ${data.planning_search_size}.`);
    if (data.upstream_stored_hits != null) bits.push(`Upstream hits stored: ${data.upstream_stored_hits}.`);
    if (data.stored_row_count != null) bits.push(`CSV rows: ${data.stored_row_count}.`);
    if (data.store_path || data.db_path) bits.push(`Store: ${data.store_path || data.db_path}.`);
    if (statusEl) statusEl.textContent = bits.join(" ");

    console.info("[planning] Rendered table", {
      rows: rows.length,
      columns: columns.length,
      store: data.store_path || data.db_path,
      stored_row_count: data.stored_row_count,
    });
  } catch (err) {
    console.error("[planning]", err);
    theadRow.innerHTML = "";
    const eth = document.createElement("th");
    eth.scope = "col";
    eth.textContent = "Error";
    theadRow.appendChild(eth);

    tbody.innerHTML = "";
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.className = "muted";
    td.textContent = err instanceof Error ? err.message : String(err);
    tr.appendChild(td);
    tbody.appendChild(tr);

    if (statusEl) statusEl.textContent = "Request failed — see table.";
  }
}

window.refreshPlanningPage = refreshPlanningPage;
