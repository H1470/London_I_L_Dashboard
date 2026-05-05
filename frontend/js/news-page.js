import { fetchNews } from "./api.js";

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function refreshNewsPage() {
  const list = document.getElementById("news-feed-list");
  const status = document.getElementById("news-feed-status");
  if (!list || !status) return;

  status.hidden = false;
  status.textContent = "Loading…";
  list.innerHTML = "";

  try {
    const data = await fetchNews();
    const stories = data.stories || [];
    if (stories.length === 0) {
      status.textContent = "No stories yet. Run a sync (POST /api/news/sync or python -m app.jobs.news_sync) after configuring IMAP.";
      list.innerHTML = "";
      return;
    }
    status.hidden = true;
    list.innerHTML = stories
      .map((s) => {
        const dt = s.received_at ? new Date(s.received_at).toLocaleString("en-GB") : "";
        return `<li class="news-feed-item">
          <time datetime="${escapeHtml(s.received_at || "")}">${escapeHtml(dt)}</time>
          <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.headline)}</a>
        </li>`;
      })
      .join("");
  } catch (e) {
    status.textContent = String(e.message || e);
  }
}
