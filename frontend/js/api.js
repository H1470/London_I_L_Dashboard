/**
 * Small same-origin fetch helpers (expects UI and API on one origin, e.g. FastAPI
 * serving ``frontend/``). Throws on non-OK HTTP.
 */

export async function fetchSummary(query) {
  const url = new URL("/api/summary", window.location.origin);
  if (query) url.searchParams.set("q", query);
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function fetchIndices() {
  const res = await fetch(`${window.location.origin}/api/indices`);
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function fetchNews() {
  const res = await fetch(`${window.location.origin}/api/news`);
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}
