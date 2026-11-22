// Общие помощники: запросы к API, экранирование, автокомплит офферов.

async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) detail = detail.map(d => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("\n");
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return data;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function showMsg(el, text, ok) {
  el.className = "msg " + (ok ? "ok" : "err");
  el.innerHTML = text;
  el.hidden = false;
}

// Автокомплит: input + выпадающий список, выбранный id кладётся в input.dataset.offerId
function offerAutocomplete(input, onPick) {
  const list = document.createElement("div");
  list.className = "ac-list";
  input.parentElement.classList.add("ac");
  input.parentElement.appendChild(list);
  let timer = null, items = [], active = -1;

  function render() {
    list.innerHTML = items.map((o, i) =>
      `<div data-i="${i}" class="${i === active ? "active" : ""}"><b>[${o.id}]</b> ${esc(o.name)}</div>`).join("")
      || `<div class="muted">Ничего не найдено</div>`;
    list.style.display = "block";
  }
  function pick(i) {
    const offer = items[i];
    if (!offer) return;
    input.value = `[${offer.id}] ${offer.name}`;
    input.dataset.offerId = offer.id;
    list.style.display = "none";
    onPick && onPick(offer);
  }
  async function search() {
    try {
      items = await api("GET", "/api/offers?limit=20&q=" + encodeURIComponent(input.value.replace(/^\[\d+\]\s*/, "")));
      active = -1;
      render();
    } catch (e) { list.innerHTML = `<div class="muted">${esc(e.message)}</div>`; list.style.display = "block"; }
  }
  input.addEventListener("input", () => {
    delete input.dataset.offerId;
    clearTimeout(timer);
    timer = setTimeout(search, 200);
  });
  input.addEventListener("focus", search);
  input.addEventListener("keydown", e => {
    if (list.style.display !== "block") return;
    if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length - 1); render(); e.preventDefault(); }
    if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
    if (e.key === "Enter" && active >= 0) { pick(active); e.preventDefault(); }
    if (e.key === "Escape") list.style.display = "none";
  });
  list.addEventListener("mousedown", e => {
    const row = e.target.closest("[data-i]");
    if (row) { pick(Number(row.dataset.i)); e.preventDefault(); }
  });
  input.addEventListener("blur", () => setTimeout(() => (list.style.display = "none"), 150));
}

async function markFakeMode() {
  try {
    const meta = await api("GET", "/api/meta");
    if (meta.fake) document.getElementById("fake-badge").hidden = false;
    return meta;
  } catch (e) { return null; }
}
