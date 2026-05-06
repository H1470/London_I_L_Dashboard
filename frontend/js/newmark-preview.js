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

export async function refreshNewmarkPreview() {
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
    const res = await fetch("/api/newmark/preview?limit=100&skip_region_filter=true", { cache: "no-store" });
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
    const filt = data.filter?.applied ? "region filter on" : "all rows (no region filter)";
    const extra = total != null && pool != null ? ` — ${n} of ${pool} in preview slice (${total} in table, ${filt})` : "";
    setStatus(`Showing ${n} rows × ${cols} columns from ${data.table || "table"}${extra}.`);
  } catch (e) {
    setStatus(`Could not load preview: ${e?.message || e}`);
  }
}

