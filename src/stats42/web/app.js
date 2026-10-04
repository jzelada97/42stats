"use strict";

/* ---------------------------------------------------------------- secciones */
const RES_NAMES = { users: "alumnos", cursus_users: "cursus", projects: "proyectos", events: "eventos", exams: "exámenes",
  project_users: "intentos de proyecto", quests: "milestones", quest_users: "milestones de alumnos", evaluations: "evaluaciones", locations: "sesiones de ordenador" };

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
    [fmt(o.at_risk), `con fecha de blackhole (API) en menos de ${o.risk_days} días`],
    [fmt(o.cursus_graduated), "graduados (alumni)"],
    [fmt(o.cursus_closed), "cerraron el cursus sin graduarse"],
  ]);
}

function renderLevels(d) {
  if (!d.length) return empty(["levels"], waiting);
  columns($("levels"), d.map((x) => ({ label: String(x.level), value: x.count })), { tip: (x) => `Nivel ${esc(x.label)}: <b>${fmt(x.value)}</b> alumnos`, labelEvery: 1 });
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
    ? table(["Año", "Entraron", "En el cursus", "Activos", "Graduados", "Cerraron sin graduarse", "% que cerró", "Nivel medio"],
        d.map((c) => [esc(c.year), fmt(c.pool), fmt(c.in_cursus), fmt(c.current), fmt(c.graduated), fmt(c.closed),
          c.in_cursus ? `${pct(c.closed / c.in_cursus)}${meter(c.closed / c.in_cursus)}` : "–", c.avg_level == null ? "–" : nf.format(c.avg_level)]))
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

function renderBlackholeHistory(b) {
  const h = b.history || [];
  if (!b.history_total) return empty(["bh-history"], waiting);
  const rows = completeMonths(h);
  columns($("bh-history"), rows.map((x) => ({ label: monthLabel(x.month), value: x.count })), {
    tip: (x) => `${esc(x.label)}: <b>${fmt(x.value)}</b> blackholeados`,
  });
  $("bh-history-table").innerHTML = table(["Mes", "Blackholeados"], rows.slice().reverse().map((x) => [monthLabel(x.month), fmt(x.count)]));
  $("bh-stale").textContent = b.stale
    ? `No se cuentan ${fmt(b.stale)} alumnos con el cursus abierto y una fecha de blackhole ya pasada. Casi todos siguen activos: esa fecha no refleja su deadline real (milestones, freeze), que la API pública no expone.`
    : "";
}

function renderMilestones(m) {
  const ids = ["rank-dist", "rank-stalled"];
  if (!m.ranks.length || !m.students) { empty([...ids, "rank-steps"], "Aún no hay datos de milestones: la carga de quests sigue en curso."); return; }
  columns($("rank-dist"), m.by_rank.map((x) => ({ label: x.label.replace("Rank ", "R"), full: x.label, value: x.count })), {
    labelEvery: 1, tip: (x) => `${esc(x.full)}: <b>${fmt(x.value)}</b> alumnos`,
  });
  $("rank-dist-table").innerHTML = table(["Rank actual", "Alumnos"], m.by_rank.map((x) => [esc(x.label), fmt(x.count)]));
  columns($("rank-stalled"), m.stalled.map((x) => ({ label: x.label.replace(" días", "d"), full: x.label, value: x.count })), {
    labelEvery: 1, tip: (x) => `${esc(x.full)}: <b>${fmt(x.value)}</b> alumnos`,
  });
  $("rank-stalled-table").innerHTML = table(["Sin validar desde hace", "Alumnos"], m.stalled.map((x) => [esc(x.label), fmt(x.count)]));
  m.steps.length
    ? hbars($("rank-steps"), m.steps.map((x) => ({ name: x.label, value: x.median_days, text: `${fmt1(x.median_days)} días · ${fmt(x.n)} alumnos` })))
    : empty(["rank-steps"], waiting);
}

function renderHabits(h) {
  if (!h.quartiles.length) return empty(["habits-chart"], "Aún no hay suficientes alumnos para comparar hábitos.");
  const short = ["Más lento", "Medio-lento", "Medio-rápido", "Más rápido"];
  columns($("habits-chart"), h.quartiles.map((q, i) => ({ label: short[i], full: q.label, value: q.median_hours_30d })), {
    labelEvery: 1, tip: (x) => `${esc(x.full)}: mediana <b>${fmt1(x.value)} h</b> en 30 días`,
  });
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
load("/api/milestones", renderMilestones, ["rank-dist", "rank-stalled", "rank-steps"]);
load("/api/habits", renderHabits, ["habits-chart"]);
get("/api/blackholes").then((b) => { renderBlackholes(b); renderBlackholeHistory(b); })
  .catch((e) => empty(["blackholes", "bh-history"], `No se pudieron cargar estos datos (${esc(e.message)}).`));
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

/* resalta en la barra la sección visible */
const links = [...document.querySelectorAll("nav a")];
const io = new IntersectionObserver((entries) => entries.forEach((en) => {
  if (en.isIntersecting) links.forEach((a) => a.setAttribute("aria-current", String(a.getAttribute("href") === "#" + en.target.id)));
}), { rootMargin: "-30% 0px -60% 0px" });
document.querySelectorAll("main > section").forEach((s) => io.observe(s));
