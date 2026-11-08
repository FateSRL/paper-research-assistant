export default function(component) {
  const { data, setTriggerValue } = component;
  const scope = String((data && data.scope) || "");
  const sources = new Map();
  for (const source of (data && data.sources) || []) {
    if (source && source.ref !== undefined) sources.set(String(source.ref), source);
  }
  if (!scope) return () => {};

  window.__d8RefStates = window.__d8RefStates || {};
  const previous = window.__d8RefStates[scope];
  if (previous && previous.card) previous.card.remove();

  let hideTimer = null;
  let activeAnchor = null;
  const card = document.createElement("div");
  card.className = "d8-ref-card";
  card.setAttribute("role", "tooltip");
  card.setAttribute("aria-hidden", "true");
  card.dataset.scope = scope;
  document.body.appendChild(card);

  function clearHideTimer() {
    if (hideTimer !== null) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  function hideCard() {
    clearHideTimer();
    activeAnchor = null;
    card.classList.remove("is-visible");
    card.setAttribute("aria-hidden", "true");
  }

  function scheduleHide() {
    clearHideTimer();
    hideTimer = setTimeout(hideCard, 180);
  }

  function positionCard(anchor) {
    const rect = anchor.getBoundingClientRect();
    const width = Math.min(360, Math.max(220, window.innerWidth - 24));
    card.style.width = width + "px";
    const left = Math.min(Math.max(8, rect.left - 6), Math.max(8, window.innerWidth - width - 8));
    card.style.left = left + "px";
    const estimatedHeight = card.offsetHeight || 230;
    let top = rect.bottom + 8;
    if (top + estimatedHeight > window.innerHeight - 8) {
      top = Math.max(8, rect.top - estimatedHeight - 8);
    }
    card.style.top = top + "px";
  }

  function buildCard(source) {
    card.replaceChildren();
    const title = document.createElement("p");
    title.className = "d8-ref-card-title";
    title.textContent = source.title || "原论文";
    const meta = document.createElement("p");
    meta.className = "d8-ref-card-meta";
    meta.textContent = "PDF 文件页序 " + (source.page || "未知") + "（从 1 开始计数）";
    const text = document.createElement("p");
    text.className = "d8-ref-card-text";
    text.textContent = source.text || "（未保存原文片段）";
    const actions = document.createElement("div");
    actions.className = "d8-ref-card-actions";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "d8-ref-card-button";
    button.textContent = source.available === false ? "预览不可用" : "在 PDF 中查看";
    button.disabled = source.available === false;
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      hideCard();
      setTriggerValue("ref_click", { ref: Number(source.ref), nonce: Date.now() });
    });
    actions.appendChild(button);
    card.append(title, meta, text, actions);
  }

  function showCard(anchor) {
    const state = window.__d8RefStates[scope];
    if (!state) return;
    const prefix = "#d8-ref-" + scope + "-";
    const href = anchor.getAttribute("href") || "";
    if (!href.startsWith(prefix)) return;
    const ref = href.slice(prefix.length);
    const source = sources.get(ref);
    if (!source) return;
    activeAnchor = anchor;
    clearHideTimer();
    buildCard(source);
    card.classList.add("is-visible");
    card.setAttribute("aria-hidden", "false");
    card.style.left = "0px";
    card.style.top = "0px";
    positionCard(anchor);
  }

  function bindAnchor(anchor) {
    if (anchor.dataset.d8RefScope === scope) return;
    const prefix = "#d8-ref-" + scope + "-";
    const href = anchor.getAttribute("href") || "";
    if (!href.startsWith(prefix)) return;
    const ref = href.slice(prefix.length);
    const source = sources.get(ref);
    if (!source) return;
    anchor.dataset.d8RefScope = scope;
    anchor.classList.add("d8-ref-badge");
    anchor.setAttribute("aria-label", "引用 " + ref + "：" + (source.title || "原论文"));
    anchor.addEventListener("mouseenter", () => {
      const state = window.__d8RefStates[scope];
      if (state && state.show) state.show(anchor);
    });
    anchor.addEventListener("focus", () => {
      const state = window.__d8RefStates[scope];
      if (state && state.show) state.show(anchor);
    });
    anchor.addEventListener("mouseleave", () => {
      const state = window.__d8RefStates[scope];
      if (state && state.scheduleHide) state.scheduleHide();
    });
    anchor.addEventListener("blur", () => {
      const state = window.__d8RefStates[scope];
      if (state && state.scheduleHide) state.scheduleHide();
    });
    anchor.addEventListener("click", (event) => event.preventDefault());
  }

  function bindAll() {
    const prefix = "#d8-ref-" + scope + "-";
    document.querySelectorAll('a[href^="' + prefix + '"]').forEach(bindAnchor);
  }

  card.addEventListener("mouseenter", clearHideTimer);
  card.addEventListener("mouseleave", scheduleHide);
  card.addEventListener("click", (event) => event.stopPropagation());

  const observer = new MutationObserver(bindAll);
  observer.observe(document.body, { childList: true, subtree: true });
  window.__d8RefStates[scope] = {
    card: card,
    sources: sources,
    show: showCard,
    scheduleHide: scheduleHide,
    hide: hideCard
  };
  bindAll();
  setTimeout(bindAll, 0);
  requestAnimationFrame(bindAll);

  function onScroll() {
    if (activeAnchor) hideCard();
  }
  window.addEventListener("scroll", onScroll, true);
  window.addEventListener("resize", onScroll);
  document.addEventListener("pointerdown", (event) => {
    if (!card.contains(event.target)) hideCard();
  }, true);

  function cleanup() {
    observer.disconnect();
    clearHideTimer();
    window.removeEventListener("scroll", onScroll, true);
    window.removeEventListener("resize", onScroll);
    card.remove();
    if (window.__d8RefStates[scope] && window.__d8RefStates[scope].card === card) {
      delete window.__d8RefStates[scope];
    }
  }

  return cleanup;
}