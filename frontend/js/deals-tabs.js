/**
 * Deals tracker: two Power BI iframes (Genesis + Map). Only one has .is-active (visible).
 * `window.activateDealsPbiTab` is set for inline onclick on tab buttons (reliable in all browsers).
 */

function tabButtons(root) {
  return root.querySelectorAll(".deals-tab[data-deals-tab]");
}

function activateDealsPbiTab(key) {
  const root = document.getElementById("deals-tracker");
  if (!root) return;

  const genesis = root.querySelector("#deals-pbi-genesis");
  const mapFrame = root.querySelector("#deals-pbi-map");
  if (!genesis || !mapFrame) return;

  const showGenesis = key === "genesis";
  const showMap = key === "map";
  if (!showGenesis && !showMap) return;

  genesis.classList.toggle("is-active", showGenesis);
  mapFrame.classList.toggle("is-active", showMap);
  genesis.setAttribute("aria-hidden", showGenesis ? "false" : "true");
  mapFrame.setAttribute("aria-hidden", showMap ? "false" : "true");

  tabButtons(root).forEach((btn) => {
    const k = btn.getAttribute("data-deals-tab") || "";
    const on = k === key;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
}

export function initDealsTrackerTabs() {
  window.activateDealsPbiTab = activateDealsPbiTab;

  const root = document.getElementById("deals-tracker");
  if (!root) return;

  const genesis = root.querySelector("#deals-pbi-genesis");
  const mapFrame = root.querySelector("#deals-pbi-map");
  if (!genesis || !mapFrame) return;

  genesis.setAttribute("aria-hidden", "false");
  mapFrame.setAttribute("aria-hidden", "true");
}
