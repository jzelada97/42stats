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
  tipEl.innerHTML = html;
  tipEl.style.opacity = 1;
  const r = tipEl.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY + 14;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
  tipEl.style.left = Math.max(8, x) + "px";
  tipEl.style.top = Math.max(8, y) + "px";
}
const hideTip = () => { tipEl.style.opacity = 0; };
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
      if (hh > 0) svg += `<path class="bar" d="M${x},${m.t + ih} V${yt + r} Q${x},${yt} ${x + r},${yt} H${x + bw - r} Q${x + bw},${yt} ${x + bw},${yt + r} V${m.t + ih} Z"/>`;
      if (i === top && d.value > 0) svg += `<text class="lbl" x="${x + bw / 2}" y="${yt - 6}" text-anchor="middle">${fmt(d.value)}</text>`;
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

/* ---------------------------------------------------------------- secciones */
const RES_NAMES = { users: "alumnos", cursus_users: "cursus", projects: "proyectos", events: "eventos", exams: "exámenes",
  project_users: "intentos de proyecto", evaluations: "evaluaciones", locations: "sesiones de ordenador" };

function renderOverview(o) {
  const loading = $("loading");
  loading.hidden = !(o.loading && o.loading.length);
  if (!loading.hidden)
    loading.innerHTML = `<b>Carga inicial en curso.</b> Aún se están descargando: ${o.loading.map((r) => RES_NAMES[r] || r).join(", ")}. `
      + "Hasta que termine, algunas cifras de esas secciones son parciales.";
  $("hero").textContent = fmt(o.cursus_current);
  $("updated").textContent = o.last_sync
    ? "datos actualizados el " + new Date(o.last_sync).toLocaleString("es-ES", { dateStyle: "long", timeStyle: "short", timeZone: "Europe/Madrid" })
    : "sincronización en curso: los datos se irán completando";
  $("tiles").innerHTML = tiles([
    [o.avg_level == null ? "–" : nf.format(o.avg_level), "nivel medio"],
    [fmt(o.at_risk), `con blackhole en menos de ${o.risk_days} días`],
    [fmt(o.students), "alumnos registrados"],
    [fmt(o.cursus_blackholed), "blackholeados (histórico)"],
  ]);
}

function renderLevels(d) {
  if (!d.length) return empty(["levels"], waiting);
  columns($("levels"), d.map((x) => ({ label: String(x.level), value: x.count })), { tip: (x) => `Nivel ${x.label}: <b>${fmt(x.value)}</b> alumnos`, labelEvery: 1 });
  $("levels-table").innerHTML = table(["Nivel", "Alumnos"], d.map((x) => [x.level, fmt(x.count)]));
}

/** El mes en curso está incompleto y haría caer la serie: se deja fuera. */
const currentMonth = new Date().toISOString().slice(0, 7);
const completeMonths = (rows) => rows.filter((r) => r.month !== currentMonth);

function renderSignups(d) {
  d = completeMonths(d);
  if (d.length < 2) return empty(["signups"], waiting);
  lineChart($("signups"), d.map((x) => ({ label: x.month, value: x.count })), { xlabel: (x) => monthLabel(x.label), tip: (x) => `${monthLabel(x.label)}: <b>${fmt(x.value)}</b> altas` });
  $("signups-table").innerHTML = table(["Mes", "Altas"], d.slice().reverse().map((x) => [monthLabel(x.month), fmt(x.count)]));
}

function renderCohorts(d) {
  $("cohorts").innerHTML = d.length
    ? table(["Año", "Entraron", "En el cursus", "Siguen abiertos", "Blackholeados", "Baja antes", "Retención", "Nivel medio"],
        d.map((c) => [esc(c.year), fmt(c.pool), fmt(c.in_cursus), fmt(c.current), fmt(c.blackholed), fmt(c.dropped),
          `${pct(c.retention)}${meter(c.retention)}`, c.avg_level == null ? "–" : nf.format(c.avg_level)]))
    : `<div class="empty">${waiting}</div>`;
}

const weekLabel = (iso) => `${+iso.slice(8)} ${MONTHS[+iso.slice(5, 7) - 1]}`;
function renderBlackholes(b) {
  if (!b.upcoming) return empty(["blackholes"], waiting);
  columns($("blackholes"), b.weeks.map((w) => ({ label: weekLabel(w.week), value: w.count, week: w.week })), {
    tip: (x) => `Semana del ${esc(x.label)}: <b>${fmt(x.value)}</b> alumnos`,
  });
  $("blackholes-table").innerHTML = table(["Semana del", "Alumnos"], b.weeks.map((w) => [weekLabel(w.week), fmt(w.count)]))
    + (b.later ? `<p class="sub">Y ${fmt(b.later)} alumnos con el blackhole más adelante.</p>` : "");
}

function renderAttendance(a) {
  const ids = ["heatmap", "daily", "durations", "seatmap"];
  if (!a.sessions) { $("att-tiles").innerHTML = ""; return empty(ids, "Aún no hay sesiones: la carga del histórico sigue en curso."); }
  $("att-tiles").innerHTML = tiles([
    [fmt(a.total_hours), "horas de uso", "h"],
    [fmt(a.unique_users), "alumnos distintos"],
    [duration(a.avg_session_min), "duración media de sesión"],
    [a.peak ? `${DAYS[a.peak.weekday]} ${String(a.peak.hour).padStart(2, "0")}:00` : "–", a.peak ? `hora punta · ${fmt1(a.peak.value)} puestos de media` : "hora punta"],
  ]);
  heatmap($("heatmap"), a.heatmap);
  lineChart($("daily"), a.daily.map((d) => ({ label: d.date, value: d.hours, users: d.users })), {
    xlabel: (x) => dayLabel(x.label), tip: (x) => `${dayLabel(x.label)}: <b>${fmt1(x.value)} h</b> · ${fmt(x.users)} alumnos`,
  });
  $("daily-table").innerHTML = table(["Día", "Horas", "Alumnos"], a.daily.slice().reverse().map((d) => [dayLabel(d.date), fmt1(d.hours), fmt(d.users)]));
  columns($("durations"), a.durations.map((d) => ({ label: d.label, value: d.count })), { labelEvery: 1, tip: (x) => `${esc(x.label)}: <b>${fmt(x.value)}</b> sesiones` });
  $("durations-table").innerHTML = table(["Duración", "Sesiones"], a.durations.map((d) => [esc(d.label), fmt(d.count)]));
  a.seats.length ? seatMap($("seatmap"), a.seats) : empty(["seatmap"], "Sin datos de puestos.");
}

/* proyectos: un cuadro por cursus, tablas ordenables y filtro común */
const PCOLS = [
  ["name", "Proyecto", false], ["attempts", "Intentos", true], ["in_progress", "En curso", true], ["finished", "Terminados", true],
  ["validation_rate", "Validación", true], ["avg_mark", "Nota media", true], ["median_days", "Mediana (días)", true],
];
const pstate = { groups: [], key: "attempts", dir: -1, q: "" };

function projectRows(g, q) {
  return g.rows.filter((r) => !q || r.name.toLowerCase().includes(q)).sort((a, b) => {
    const x = a[pstate.key], y = b[pstate.key];
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * pstate.dir;
  });
}
function projectTable(rows) {
  const head = PCOLS.map(([k, l, n]) => `<th class="sort ${n ? "n" : ""}" data-k="${k}" tabindex="0" ${pstate.key === k ? `aria-sort="${pstate.dir > 0 ? "ascending" : "descending"}"` : ""}>${l}</th>`).join("");
  const body = rows.map((p) => `<tr><td>${esc(p.name)}</td><td class="n">${fmt(p.attempts)}</td><td class="n">${fmt(p.in_progress)}</td><td class="n">${fmt(p.finished)}</td>`
    + `<td class="n">${pct(p.validation_rate)}${meter(p.validation_rate)}</td><td class="n">${p.avg_mark == null ? "–" : fmt1(p.avg_mark)}</td><td class="n">${p.median_days == null ? "–" : fmt1(p.median_days)}</td></tr>`).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}
function renderProjectsTable() {
  const q = pstate.q.trim().toLowerCase();
  const cards = pstate.groups.map((g, i) => {
    const rows = projectRows(g, q);
    if (q && !rows.length) return "";
    const open = q ? true : i < 3;  // los más activos abiertos; al buscar se abren los que coinciden
    return `<details class="card cursus" ${open ? "open" : ""}><summary><h3>${g.names.map(esc).join(" · ")}</h3>`
      + `<span class="sub">${fmt(g.projects_count)} proyectos · ${fmt(g.attempts)} intentos</span></summary>`
      + `<div class="wrap">${projectTable(rows)}</div></details>`;
  }).join("");
  $("projects").innerHTML = cards || `<div class="empty card">Ningún proyecto coincide.</div>`;
}
function renderProjects(d) {
  if (!d.length) return empty(["projects"], "Aún no hay proyectos con intentos suficientes: la carga sigue en curso.");
  pstate.groups = d;
  renderProjectsTable();
}
function renderProjectsMonthly(d) {
  d = completeMonths(d);
  if (d.length < 2) return empty(["pm"], waiting);
  columns($("pm"), d.map((x) => ({ label: monthLabel(x.month), value: x.validated + x.failed, v: x.validated, f: x.failed })), {
    tip: (x) => `${esc(x.label)}: <b>${fmt(x.value)}</b> terminados<br>${fmt(x.v)} validados · ${fmt(x.f)} no validados`,
  });
  $("pm-table").innerHTML = table(["Mes", "Validados", "No validados"], d.slice().reverse().map((x) => [monthLabel(x.month), fmt(x.validated), fmt(x.failed)]));
}

function renderEvaluations(e) {
  if (!e.total) { $("ev-tiles").innerHTML = ""; return empty(["ev-monthly", "ev-flags", "ev-marks"], "Aún no hay evaluaciones: la carga sigue en curso."); }
  $("ev-tiles").innerHTML = tiles([
    [fmt(e.total), "evaluaciones completadas"],
    [fmt1(e.avg_mark), "nota media"],
    [pct(e.positive_share), "con resultado positivo"],
    [fmt(e.active_correctors_90d), "alumnos evaluando (90 días)"],
    [fmt(e.scheduled), "programadas ahora"],
  ]);
  e.monthly = completeMonths(e.monthly);
  if (e.monthly.length > 1) {
    lineChart($("ev-monthly"), e.monthly.map((x) => ({ label: x.month, value: x.count, avg: x.avg_mark })), {
      xlabel: (x) => monthLabel(x.label), tip: (x) => `${monthLabel(x.label)}: <b>${fmt(x.value)}</b> evaluaciones · nota media ${fmt1(x.avg)}`,
    });
    $("ev-monthly-table").innerHTML = table(["Mes", "Evaluaciones", "Nota media"], e.monthly.slice().reverse().map((x) => [monthLabel(x.month), fmt(x.count), fmt1(x.avg_mark)]));
  }
  hbars($("ev-flags"), e.flags.map((f) => ({ name: f.name, value: f.count, text: `${fmt(f.count)} · ${pct(f.count / e.total)}` })));
  columns($("ev-marks"), e.marks.map((m) => ({ label: m.label, value: m.count })), { labelEvery: 1, tip: (x) => `Nota ${esc(x.label)}: <b>${fmt(x.value)}</b> evaluaciones` });
}

const dateFmt = new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Madrid" });
const timeFmt = new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" });
const agendaList = (items, kind) => items.length
  ? items.map((i) => `<li><time datetime="${esc(i.begin_at)}">${dateFmt.format(new Date(i.begin_at))}<br>${timeFmt.format(new Date(i.begin_at))}</time>`
      + `<div><div class="t">${esc(i.name)}</div><div class="m">${[kind ? esc(i.kind) : null, i.location ? esc(i.location) : null].filter(Boolean).join(" · ") || "&nbsp;"}</div></div>`
      + `<div class="c">${i.subscribers == null ? "" : `${fmt(i.subscribers)}${i.max_people ? ` / ${fmt(i.max_people)}` : ""} <span class="m">inscritos</span>`}</div></li>`).join("")
  : `<li><span class="empty">No hay nada programado.</span></li>`;

function renderEvents(x) {
  $("up-events").innerHTML = agendaList(x.upcoming_events, true);
  $("up-exams").innerHTML = agendaList(x.upcoming_exams, false);
  if (x.events_monthly.length > 1) {
    columns($("events-monthly"), x.events_monthly.map((m) => ({ label: monthLabel(m.month), value: m.count })), { tip: (d) => `${esc(d.label)}: <b>${fmt(d.value)}</b> eventos` });
    $("events-monthly-table").innerHTML = table(["Mes", "Eventos"], x.events_monthly.slice().reverse().map((m) => [monthLabel(m.month), fmt(m.count)]));
  } else empty(["events-monthly"], waiting);
  x.kinds.length
    ? hbars($("kinds"), x.kinds.map((k) => ({ name: k.kind, value: k.count, text: `${fmt(k.count)} · ${fmt1(k.avg_subscribers)} insc.` })))
    : empty(["kinds"], waiting);
}

/* ---------------------------------------------------------------- arranque */
function load(path, render, ids) {
  return get(path).then(render).catch((e) => empty(ids, `No se pudieron cargar estos datos (${esc(e.message)}). Inténtalo de nuevo en unos minutos.`));
}
load("/api/overview", renderOverview, ["tiles"]);
load("/api/levels", renderLevels, ["levels"]);
load("/api/signups", renderSignups, ["signups"]);
load("/api/cohorts", renderCohorts, ["cohorts"]);
load("/api/blackholes", renderBlackholes, ["blackholes"]);
load("/api/attendance", renderAttendance, ["heatmap", "daily", "durations", "seatmap"]);
load("/api/projects", renderProjects, ["projects"]);
load("/api/projects/monthly", renderProjectsMonthly, ["pm"]);
load("/api/evaluations", renderEvaluations, ["ev-monthly", "ev-flags", "ev-marks"]);
load("/api/events", renderEvents, ["up-events", "up-exams", "events-monthly", "kinds"]);

$("psearch").addEventListener("input", (e) => { pstate.q = e.target.value; renderProjectsTable(); });
$("projects").addEventListener("click", (e) => {
  const th = e.target.closest("th[data-k]");
  if (!th) return;
  const open = [...document.querySelectorAll("#projects details")].map((d) => d.open);  // conserva qué cuadros están abiertos
  pstate.dir = pstate.key === th.dataset.k ? -pstate.dir : (th.dataset.k === "name" ? 1 : -1);
  pstate.key = th.dataset.k;
  renderProjectsTable();
  document.querySelectorAll("#projects details").forEach((d, i) => { if (open[i] != null) d.open = open[i]; });
});
$("projects").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.click?.(); });

/* tema: auto / claro / oscuro (se recuerda en este navegador) */
const MODES = ["auto", "light", "dark"], LABELS = { auto: "tema: auto", light: "tema: claro", dark: "tema: oscuro" };
let mode = "auto";
try { mode = localStorage.getItem("theme") || "auto"; } catch (_) { /* sin almacenamiento */ }
const applyMode = () => {
  mode === "auto" ? document.documentElement.removeAttribute("data-theme") : document.documentElement.setAttribute("data-theme", mode);
  $("theme").textContent = LABELS[mode];
};
$("theme").addEventListener("click", () => {
  mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
  try { localStorage.setItem("theme", mode); } catch (_) { /* ignorar */ }
  applyMode();
});
applyMode();

/* resalta en la barra la sección visible */
const links = [...document.querySelectorAll("nav a")];
const io = new IntersectionObserver((entries) => entries.forEach((en) => {
  if (en.isIntersecting) links.forEach((a) => a.setAttribute("aria-current", String(a.getAttribute("href") === "#" + en.target.id)));
}), { rootMargin: "-30% 0px -60% 0px" });
document.querySelectorAll("main > section").forEach((s) => io.observe(s));
