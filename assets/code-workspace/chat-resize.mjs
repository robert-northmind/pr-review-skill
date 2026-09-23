/** Desktop rail sizing. The viewport clamp never overwrites the saved preference. */
const STORAGE_KEY = 'pr-code-chat-width';
const DEFAULT_WIDTH = 420;
export function installChatResize(panel, handle, container) {
  let preferred = DEFAULT_WIDTH, drag = null;
  try {
    const saved = Number(localStorage.getItem(STORAGE_KEY));
    if (Number.isFinite(saved) && saved >= 320) preferred = Math.min(900, saved);
  } catch {}
  const desktop = matchMedia('(min-width: 751px)');
  const limits = () => ({min:320, max:Math.max(320, Math.min(900, container.clientWidth - 360))});
  const clamp = value => Math.round(Math.max(limits().min, Math.min(limits().max, value)));
  function apply() {
    const width = clamp(preferred);
    panel.style.setProperty('--chat-width', width + 'px');
    handle.setAttribute('aria-valuemin', limits().min);
    handle.setAttribute('aria-valuemax', limits().max);
    handle.setAttribute('aria-valuenow', width);
    handle.setAttribute('aria-valuetext', width + ' pixels');
    handle.tabIndex = desktop.matches ? 0 : -1;
  }
  function persist() {
    try { localStorage.setItem(STORAGE_KEY, String(preferred)); } catch {}
  }
  function finish(cancel = false) {
    if (!drag) return;
    const previous = drag; drag = null;
    if (cancel) preferred = previous.preferred;
    document.body.classList.remove('resizing-chat');
    if (handle.hasPointerCapture(previous.id)) handle.releasePointerCapture(previous.id);
    apply();
    if (!cancel) persist();
  }
  handle.addEventListener('pointerdown', event => {
    if (!desktop.matches || event.button !== 0 || drag) return;
    event.preventDefault(); handle.focus();
    drag = {id:event.pointerId, x:event.clientX, width:panel.getBoundingClientRect().width, preferred};
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add('resizing-chat');
  });
  handle.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.id) return;
    preferred = clamp(drag.width + drag.x - event.clientX); apply();
  });
  handle.addEventListener('pointerup', () => finish());
  handle.addEventListener('pointercancel', () => finish(true));
  handle.addEventListener('lostpointercapture', () => finish());
  handle.addEventListener('keydown', event => {
    if (event.key === 'Escape' && drag) { event.preventDefault(); event.stopPropagation(); finish(true); return; }
    if (!desktop.matches || !['ArrowLeft','ArrowRight','Home','End','Enter'].includes(event.key)) return;
    event.preventDefault();
    const step = event.shiftKey ? 80 : 24;
    preferred = event.key === 'Enter' ? DEFAULT_WIDTH : event.key === 'Home' ? limits().min : event.key === 'End' ? limits().max : clamp(clamp(preferred) + (event.key === 'ArrowLeft' ? step : -step));
    apply(); persist();
  });
  handle.addEventListener('dblclick', () => { preferred = DEFAULT_WIDTH; apply(); persist(); });
  new ResizeObserver(() => { if (!desktop.matches) finish(true); apply(); }).observe(container);
  apply();
}
