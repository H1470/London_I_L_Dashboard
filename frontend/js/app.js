import { loadDashboardData, loadTrialSummary } from "./dashboard.js";
import { initDealsTrackerTabs } from "./deals-tabs.js";
import { refreshNewmarkPreview } from "./newmark-preview.js";
import { refreshNewsPage } from "./news-page.js";

const pageMeta = {
  landing: {
    title: "London I&L Information Platform",
    subtitle: "Landing page",
  },
  dashboard: {
    title: "London I&L Information Platform",
    subtitle: "Dashboard",
  },
  "bought-sold": {
    title: "Newmark Bought & Sold List",
    subtitle: "Transaction intelligence",
  },
  "deals-tracker": {
    title: "London I&L Deals Tracker",
    subtitle: "Genesis / Power BI tracker",
  },
  development: {
    title: "London I&L Development",
    subtitle: "Planning and pipeline intelligence",
  },
  news: {
    title: "Latest London I&L News",
    subtitle: "Market alerts",
  },
  sources: {
    title: "Newmark Research",
    subtitle: "Platform inputs",
  },
  uploads: {
    title: "Uploads",
    subtitle: "Uploaded files and datasets",
  },
};

export function showPage(id) {
  document.querySelectorAll(".page").forEach((page) => {
    page.classList.toggle("active", page.id === id);
  });

  document.querySelectorAll(".nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === id);
  });

  const meta = pageMeta[id] || pageMeta.landing;
  document.getElementById("page-title").textContent = meta.title;
  document.getElementById("page-subtitle").textContent = meta.subtitle;

  if (id === "dashboard") {
    loadDashboardData();
    loadTrialSummary();
  }

  if (id === "news") {
    refreshNewsPage();
  }

  if (id === "bought-sold") {
    refreshNewmarkPreview();
  }

  window.scrollTo({ top: 0, behavior: "smooth" });
}

window.showPage = showPage;
window.refreshNewmarkPreview = refreshNewmarkPreview;
window.refreshNewmarkPreviewAllRows = () => refreshNewmarkPreview({ skipMapFilters: true });

document.querySelectorAll(".nav button").forEach((button) => {
  button.addEventListener("click", () => showPage(button.dataset.page));
});

initDealsTrackerTabs();

// If someone loads directly onto a page via saved state, ensure page hooks run.
const initialActive = document.querySelector(".page.active")?.id;
if (initialActive) showPage(initialActive);
