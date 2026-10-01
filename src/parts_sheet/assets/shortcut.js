export function openPartsSheet() {
  window.location.assign("/plugin/parts-sheet/");
}
// InvenTree 1.3 uses the two-argument signature for DOM-based widgets.
// A one-argument function is called as a React renderer with a context object.
export function renderPartsSheet(target, context) {
  if (!target) return;
  const link = document.createElement("a");
  link.href = "/plugin/parts-sheet/";
  link.textContent = "Open Parts Sheet";
  link.style.cssText =
    "display:flex;align-items:center;justify-content:center;height:100%;min-height:44px;background:#1971c2;color:white;border-radius:6px;text-decoration:none;font-weight:600";
  target.replaceChildren(link);
}
