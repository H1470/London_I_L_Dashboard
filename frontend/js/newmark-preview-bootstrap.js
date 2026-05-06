/**
 * Assigns Newmark preview to window before app.js runs.
 * If app.js fails on another import, the Sources preview button still works.
 */
import { refreshNewmarkPreview } from "./newmark-preview.js";

window.refreshNewmarkPreview = refreshNewmarkPreview;
window.refreshNewmarkPreviewAllRows = () => refreshNewmarkPreview({ skipMapFilters: true });
