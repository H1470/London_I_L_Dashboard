/**
 * Assigns Newmark preview helpers to ``window`` before ``app.js`` runs so inline
 * onclick handlers work even if a later module import fails.
 */
import { refreshNewmarkPreview } from "./newmark-preview.js";

window.refreshNewmarkPreview = refreshNewmarkPreview;
window.refreshNewmarkPreviewAllRows = () => refreshNewmarkPreview({ skipMapFilters: true });
