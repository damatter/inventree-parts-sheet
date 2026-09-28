export function openPartsSheet() { window.location.assign('/plugin/parts-sheet/'); }
export function renderPartsSheet(target) {
    if (!target) return;
    const link = document.createElement('a');
    link.href = '/plugin/parts-sheet/';
    link.textContent = 'Open Parts Sheet';
    link.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;min-height:44px;background:#1971c2;color:white;border-radius:6px;text-decoration:none;font-weight:600';
    target.replaceChildren(link);
}
