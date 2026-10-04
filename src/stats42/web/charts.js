"use strict";

/* ---------------------------------------------------------------- utilidades */
const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat("es-ES");
const nf1 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });
const fmt = (n) => (n == null ? "–" : nf.format(n));
const fmt1 = (n) => (n == null ? "–" : nf1.format(n));
const pct = (r) => (r == null ? "–" : Math.round(r * 100) + " %");
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];
const monthLabel = (m) => `${MONTHS[+m.slice(5) - 1]} ${m.slice(2, 4)}`;
const dayLabel = (d) => `${+d.slice(8)} ${MONTHS[+d.slice(5, 7) - 1]}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const duration = (min) => (min == null ? "–" : min >= 60 ? `${Math.floor(min / 60)} h ${min % 60} min` : `${min} min`);

async function get(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
  return r.json();
}

const tipEl = $("tip");
function showTip(ev, html) {
  if (!tipEl) return;
  tipEl.innerHTML = html;
  tipEl.style.opacity = 1;
  const r = tipEl.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY + 14;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
  tipEl.style.left = Math.max(8, x) + "px";
  tipEl.style.top = Math.max(8, y) + "px";
}
const hideTip = () => { if (tipEl) tipEl.style.opacity = 0; };
addEventListener("scroll", hideTip, { passive: true });

/** Dibuja `draw(anchoPx)` ahora y cada vez que cambia el ancho del contenedor. */
function host(el, draw) {
  let last = 0;
  // Por debajo de 160 px el layout aún no está listo (o el panel está colapsado): se espera al siguiente cambio de tamaño.
  const run = () => { const w = Math.floor(el.clientWidth); if (w >= 160) { last = w; draw(w); } };
  new ResizeObserver(() => { if (Math.floor(el.clientWidth) !== last) run(); }).observe(el);
  run();
}

function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v)), f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

/** Marco de un gráfico de ejes: rejilla fina, ticks redondos, línea base. */
function frame(w, h, m, max) {
  const iw = w - m.l - m.r, ih = h - m.t - m.b;
  const y = (v) => m.t + ih - (v / max) * ih;
  const ticks = max <= 4 ? Math.max(1, Math.round(max)) : 4;
  let s = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img">`;
  for (let i = 0; i <= ticks; i++) {
    const v = (max / ticks) * i;
    s += `<line class="${i ? "grid" : "axis"}" x1="${m.l}" x2="${w - m.r}" y1="${y(v)}" y2="${y(v)}"/>`
      + `<text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${fmt(Math.round(v * 10) / 10)}</text>`;
  }
  return { s, iw, ih, y };
}

/* ---------------------------------------------------------------- gráficos */
/** Columnas finas (máx. 24 px) con el extremo redondeado; etiqueta solo en el máximo. */
function columns(el, data, { tip, labelEvery } = {}) {
  host(el, (w) => {
    const h = 240, m = { l: 44, r: 8, t: 18, b: 28 };
    const max = niceMax(Math.max(...data.map((d) => d.value)));
    const { s, iw, ih, y } = frame(w, h, m, max);
    const band = iw / data.length, bw = Math.min(24, band * 0.6);
    const step = labelEvery || Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(iw / 58))));
    const top = data.reduce((a, d, i) => (d.value > data[a].value ? i : a), 0);
    let svg = s;
    data.forEach((d, i) => {
      const x = m.l + band * i + (band - bw) / 2, yt = y(d.value), hh = Math.max(m.t + ih - yt, 0), r = Math.min(4, hh, bw / 2);
      if (hh > 0) svg += `<path class="bar${d.hi ? " hi" : ""}" d="M${x},${m.t + ih} V${yt + r} Q${x},${yt} ${x + r},${yt} H${x + bw - r} Q${x + bw},${yt} ${x + bw},${yt + r} V${m.t + ih} Z"/>`;
      if (d.hi) svg += `<text class="lbl" x="${x + bw / 2}" y="${yt - 6}" text-anchor="middle">tú</text>`;
      else if (i === top && d.value > 0 && !data.some((x) => x.hi)) svg += `<text class="lbl" x="${x + bw / 2}" y="${yt - 6}" text-anchor="middle">${fmt(d.value)}</text>`;
      if (i % step === 0) svg += `<text x="${x + bw / 2}" y="${h - 8}" text-anchor="middle">${esc(d.label)}</text>`;
      svg += `<rect class="hit" data-i="${i}" x="${m.l + band * i}" y="${m.t}" width="${band}" height="${ih}"/>`;
    });
    el.innerHTML = svg + "</svg>";
    el.querySelectorAll(".hit").forEach((r) => {
      const d = data[+r.dataset.i];
      r.addEventListener("pointermove", (e) => showTip(e, tip ? tip(d) : `${esc(d.label)}: <b>${fmt(d.value)}</b>`));
      r.addEventListener("pointerleave", hideTip);
    });
  });
}

/** Línea de 2 px con relleno al 10 %, punto final con anillo y cruz con tooltip. */
function lineChart(el, data, { tip, xlabel } = {}) {
  host(el, (w) => {
    const h = 240, m = { l: 44, r: 14, t: 18, b: 28 };
    const max = niceMax(Math.max(...data.map((d) => d.value)));
    const { s, iw, ih, y } = frame(w, h, m, max);
    const x = (i) => m.l + (data.length === 1 ? iw / 2 : (iw * i) / (data.length - 1));
    const last = data.length - 1, pts = data.map((d, i) => `${x(i)},${y(d.value)}`);
    const step = Math.ceil(data.length / Math.max(2, Math.floor(iw / 64)));
    let svg = s;
    data.forEach((d, i) => { if (i % step === 0) svg += `<text x="${x(i)}" y="${h - 8}" text-anchor="middle">${esc(xlabel ? xlabel(d) : d.label)}</text>`; });
    svg += `<path class="area" d="M${x(0)},${y(0)} L${pts.join(" L")} L${x(last)},${y(0)} Z"/><polyline class="line" points="${pts.join(" ")}"/>`;
    svg += `<circle class="dot" cx="${x(last)}" cy="${y(data[last].value)}" r="4"/>`;
    svg += `<line class="cross" id="cx" y1="${m.t}" y2="${m.t + ih}" style="display:none"/><circle class="dot" id="cd" r="4" style="display:none"/>`;
    svg += `<rect class="hit" id="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}"/></svg>`;
    el.innerHTML = svg;
    const cx = el.querySelector("#cx"), cd = el.querySelector("#cd"), hit = el.querySelector("#hit");
    hit.addEventListener("pointermove", (e) => {
      const r = hit.getBoundingClientRect();
      const i = Math.max(0, Math.min(last, Math.round(((e.clientX - r.left) / r.width) * last)));
      cx.setAttribute("x1", x(i)); cx.setAttribute("x2", x(i)); cx.style.display = "";
      cd.setAttribute("cx", x(i)); cd.setAttribute("cy", y(data[i].value)); cd.style.display = "";
      showTip(e, tip ? tip(data[i]) : `${esc(data[i].label)}: <b>${fmt(data[i].value)}</b>`);
    });
    hit.addEventListener("pointerleave", () => { cx.style.display = "none"; cd.style.display = "none"; hideTip(); });
  });
}

const heat = (v, max) => `color-mix(in srgb, var(--accent) ${v > 0 ? 8 + 92 * Math.min(1, v / max) : 5}%, var(--surface))`;

/** Mapa de calor día de la semana × hora. */
function heatmap(el, cells) {
  host(el, (w) => {
    const L = 34, T = 18, cw = (w - L) / 24, ch = Math.max(18, Math.min(30, cw)), h = T + ch * 7;
    const max = Math.max(...cells.map((c) => c.value), 0.1);
    let svg = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img">`;
    for (let hr = 0; hr < 24; hr += 3) svg += `<text x="${L + cw * hr + cw / 2}" y="11" text-anchor="middle">${String(hr).padStart(2, "0")}</text>`;
    DAYS.forEach((d, i) => { svg += `<text x="${L - 8}" y="${T + ch * i + ch / 2 + 4}" text-anchor="end">${d}</text>`; });
    for (const c of cells)
      svg += `<rect class="cell" data-w="${c.weekday}" data-h="${c.hour}" x="${L + cw * c.hour}" y="${T + ch * c.weekday}" width="${cw}" height="${ch}" style="fill:${heat(c.value, max)}"/>`;
    el.innerHTML = svg + "</svg>";
    el.querySelectorAll(".cell").forEach((r) => {
      const c = cells.find((x) => x.weekday === +r.dataset.w && x.hour === +r.dataset.h);
      r.addEventListener("pointermove", (e) => showTip(e, `${DAYS[c.weekday]} ${String(c.hour).padStart(2, "0")}:00 · <b>${fmt1(c.value)}</b> puestos de media`));
      r.addEventListener("pointerleave", hideTip);
    });
  });
}

/** Un panel por cluster: fila en vertical, puesto en horizontal (hosts tipo c3r5s1). */
function seatMap(el, seats) {
  const max = Math.max(...seats.map((s) => s.sessions), 1);
  const byCluster = {};
  seats.forEach((s) => ((byCluster[s.cluster] ||= []).push(s)));
  const CW = 26, CH = 16, L = 26;
  el.innerHTML = Object.keys(byCluster).sort((a, b) => a - b).map((c) => {
    const list = byCluster[c], rows = Math.max(...list.map((s) => s.row)), cols = Math.max(...list.map((s) => s.seat));
    const idx = new Map(list.map((s) => [`${s.row}-${s.seat}`, s.sessions]));
    let svg = `<svg viewBox="0 0 ${L + CW * cols} ${14 + CH * rows}" width="${L + CW * cols}" height="${14 + CH * rows}" role="img" aria-label="Cluster ${c}">`;
    for (let s = 1; s <= cols; s++) svg += `<text x="${L + CW * (s - 1) + CW / 2}" y="9" text-anchor="middle">${s}</text>`;
    for (let r = 1; r <= rows; r++) {
      svg += `<text x="${L - 6}" y="${14 + CH * (r - 1) + CH / 2 + 4}" text-anchor="end">r${r}</text>`;
      for (let s = 1; s <= cols; s++) {
        const n = idx.get(`${r}-${s}`) || 0;
        svg += `<rect class="cell" data-c="${c}" data-r="${r}" data-s="${s}" data-n="${n}" x="${L + CW * (s - 1)}" y="${14 + CH * (r - 1)}" width="${CW}" height="${CH}" style="fill:${heat(n, max)}"/>`;
      }
    }
    return `<figure><figcaption>cluster ${c}</figcaption>${svg}</svg></figure>`;
  }).join("");
  el.querySelectorAll(".cell").forEach((r) => {
    r.addEventListener("pointermove", (e) => showTip(e, `<span class="mono">c${r.dataset.c}r${r.dataset.r}s${r.dataset.s}</span> · <b>${fmt(+r.dataset.n)}</b> sesiones`));
    r.addEventListener("pointerleave", hideTip);
  });
}

/** Barras horizontales (HTML, se adaptan solas al ancho). */
function hbars(el, rows) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  el.innerHTML = rows.map((r) => `<div class="hrow"><span class="name" title="${esc(r.name)}">${esc(r.name)}</span>`
    + `<span class="track"><i style="width:${Math.max(1, (r.value / max) * 100)}%"></i></span><span class="val">${r.text ?? fmt(r.value)}</span></div>`).join("");
}

const table = (head, rows) =>
  `<table><thead><tr>${head.map((h, i) => `<th class="${i ? "n" : ""}">${h}</th>`).join("")}</tr></thead><tbody>${
    rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i ? "n" : ""}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
const meter = (r) => (r == null ? "" : `<span class="meter"><i style="width:${Math.round(r * 100)}%"></i></span>`);
const tiles = (items) => items.map(([v, l, unit]) => `<div class="tile"><div class="v">${v}${unit ? `<small>${unit}</small>` : ""}</div><div class="l">${l}</div></div>`).join("");
const empty = (ids, msg) => ids.forEach((id) => { const e = $(id); if (e) e.innerHTML = `<div class="empty">${msg}</div>`; });
const waiting = "Aún no hay datos: la carga inicial sigue en curso.";


/* ---------------------------------------------------------------- sesión y tema (comunes a todas las páginas) */
(function initShared() {
  const MODES = ["auto", "light", "dark"], LABELS = { auto: "tema: auto", light: "tema: claro", dark: "tema: oscuro" };
  let mode = "auto";
  try { mode = localStorage.getItem("theme") || "auto"; } catch (_) { /* sin almacenamiento */ }
  const btn = document.getElementById("theme");
  const apply = () => {
    mode === "auto" ? document.documentElement.removeAttribute("data-theme") : document.documentElement.setAttribute("data-theme", mode);
    if (btn) btn.textContent = LABELS[mode];
  };
  if (btn) btn.addEventListener("click", () => {
    mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
    try { localStorage.setItem("theme", mode); } catch (_) { /* ignorar */ }
    apply();
  });
  apply();

  const link = document.getElementById("auth-link");
  if (link) fetch("/api/session").then((r) => r.json()).then((u) => {
    if (u.logged_in) { link.textContent = `Mi panel · ${u.name || u.login}`; link.href = "/me"; }
    else { link.textContent = "Entrar con 42"; link.href = "/login"; }
  }).catch(() => {});
})();
