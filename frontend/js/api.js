/** Same-origin when the UI is served by FastAPI. */
export async function fetchSummary(query) {
  const url = new URL("/api/summary", window.location.origin);
  if (query) url.searchParams.set("q", query);
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}
