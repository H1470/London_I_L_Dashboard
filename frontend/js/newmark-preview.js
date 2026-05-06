/**
 * Newmark ``master_all`` table preview for the Bought & Sold page: calls ``/api/newmark/preview``.
 * Default = same filters as map; ``skipMapFilters`` loads raw merged rows for debugging.
 */
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderPreview({ columns, rows }) {
  const head = document.getElementById("newmark-preview-head");
  const body = document.getElementById("newmark-preview-body");
  if (!head || !body) return;

  head.innerHTML =
    "<tr>" + (columns || []).map((c) => `<th>${escapeHtml(c)}</th>`).join("") + "</tr>";

  const safeRows = rows || [];
  body.innerHTML =
    safeRows.length === 0
      ? `<tr><td class="muted">No rows returned.</td></tr>`
      : safeRows
          .map((r) => "<tr>" + r.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("") + "</tr>")
          .join("");
}

/**
 * @param {{ skipMapFilters?: boolean }} [options] — When true, loads raw `master_all` rows (no region / GE filters).
 * Default matches the Newmark map: London & South East + GE involvement allowed values.
 */
export async function refreshNewmarkPreview(options = {}) {
  const skipMapFilters = options.skipMapFilters === true;
  const status = document.getElementById("newmark-preview-status");
  const setStatus = (t) => {
    if (status) status.textContent = t;
  };

  const head = document.getElementById("newmark-preview-head");
  const body = document.getElementById("newmark-preview-body");
  if (!status || !head || !body) {
    // If these are missing, the container isn't mounted or ids changed.
    return;
  }

  setStatus("Loading preview…");
  try {
    const params = new URLSearchParams({ limit: "100" });
    if (skipMapFilters) params.set("skip_region_filter", "true");
    const res = await fetch(`/api/newmark/preview?${params}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data && data.ok === false) {
      renderPreview({ columns: [], rows: [] });
      setStatus(`Preview error: ${data.error || "unknown error"} (db: ${data.db_path || "?"}, table: ${data.table || "?"})`);
      return;
    }
    renderPreview(data);
    const cols = (data.columns || []).length;
    const n = (data.rows || []).length;
    const total = data.total_row_count;
    const pool = data.preview_row_count;
    const filt = data.filter?.applied
      ? "same filters as map (London / South East + GE involvement)"
      : "all rows in DB (map filters off)";
    const extra = total != null && pool != null ? ` — ${n} of ${pool} in this slice (${total} rows in table, ${filt})` : "";
    const ge = data.filter?.ge_involvement;
    let geLine = "";
    if (data.filter?.applied && ge) {
      if (ge.column) {
        geLine = ` GE involvement column: ${ge.column}.`;
      } else if (ge.disabled) {
        geLine =
          " Warning: GE involvement column not resolved — GE filter rejects every row. Check /api/newmark/schema select_row_layout and set NEWMARK_GE_INVOLVEMENT_COLUMN if needed.";
      }
    }
    setStatus(`Showing ${n} rows × ${cols} columns from ${data.table || "table"}${extra}.${geLine}`);
  } catch (e) {
    setStatus(`Could not load preview: ${e?.message || e}`);
  }
}

