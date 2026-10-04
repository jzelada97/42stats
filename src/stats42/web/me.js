"use strict";

const STATE_ICON = { good: "✓", ok: "•", warn: "!" };
const STATE_TEXT = { good: "Bien", ok: "Normal", warn: "A vigilar" };
const STATUS_ICON = { great: "✓", normal: "•", attention: "!", frozen: "❄", none: "–" };

function renderMe(d) {
  document.getElementById("me-kicker").textContent = `mi panel · ${d.login}`;
  document.getElementById("me-sub").textContent = d.pool ? `piscina ${d.pool}` : "";
  const st = document.getElementById("status");
  st.dataset.state = d.status.key;
  document.getElementById("status-chip").textContent = `${STATUS_ICON[d.status.key] || ""} ${d.status.label}`;
  document.getElementById("status-summary").textContent = d.status.summary;
  document.getElementById("facts").innerHTML = tiles([
    [d.level == null ? "–" : nf.format(d.level), "tu nivel"],
    [d.days_in_cursus == null ? "–" : fmt(d.days_in_cursus), "días en el cursus"],
    [d.milestones.length ? d.milestones[d.milestones.length - 1].label : "–", "último rank validado"],
    [fmt1(d.activity.hours_30d), "horas en 30 días"],
  ]);

  document.getElementById("signals").innerHTML = d.signals.map((x) => `
    <article class="card sig" data-state="${x.state}">
      <div class="sig-head"><span class="state" aria-label="${STATE_TEXT[x.state]}">${STATE_ICON[x.state]} ${STATE_TEXT[x.state]}</span><h3>${esc(x.label)}</h3></div>
      <div class="sig-val">${esc(x.value)}</div>
      <p class="sub">${esc(x.detail)}</p>
    </article>`).join("");

  const tips = document.getElementById("tips");
  tips.innerHTML = d.tips.map((t) => `<li>${esc(t)}</li>`).join("");
  document.getElementById("tips-card").hidden = !d.tips.length;

  const tl = document.getElementById("timeline");
  const done = d.milestones.map((m) => `<li class="done"><b>${esc(m.label)}</b><span class="mono">${esc(m.date)}</span>`
    + `<span class="sub">${m.days_from_previous == null ? "" : `${fmt(m.days_from_previous)} días desde el anterior`}</span></li>`);
  const next = d.next_milestone
    ? `<li class="next"><b>${esc(d.next_milestone.label)}</b><span class="mono">pendiente</span><span class="sub">${
        d.next_milestone.days_since_last == null ? "" : `llevas ${fmt(d.next_milestone.days_since_last)} días`}${
        d.next_milestone.typical_days == null ? "" : ` · lo habitual: ${fmt(Math.round(d.next_milestone.typical_days))}`}</span></li>` : "";
  tl.innerHTML = (done.join("") + next) || `<li class="sub">Aún no hay milestones registrados.</li>`;

  const lc = d.level_context;
  if (lc.my_bucket != null && lc.hist.length) {
    columns(document.getElementById("level-chart"), lc.hist.map((x) => ({ label: String(x.level), value: x.count, hi: x.level === lc.my_bucket })),
      { labelEvery: 1, tip: (x) => `Nivel ${esc(x.label)}: <b>${fmt(x.value)}</b> alumnos` });
    if (lc.percentile != null) document.getElementById("level-sub").textContent =
      `Alumnos con el cursus abierto por nivel. Tu ritmo (nivel por mes) supera al ${Math.round(lc.percentile * 100)} % de ellos.`;
  } else document.getElementById("level-chart").innerHTML = `<div class="empty">No hay nivel que comparar: no tienes el 42cursus abierto.</div>`;

  const w = d.activity.weekly.map((x) => ({ label: `${+x.week.slice(8)} ${MONTHS[+x.week.slice(5, 7) - 1]}`, value: x.hours }));
  columns(document.getElementById("weekly"), w, { tip: (x) => `Semana del ${esc(x.label)}: <b>${fmt1(x.value)} h</b>` });
  document.getElementById("weekly-table").innerHTML = table(["Semana del", "Horas"], w.slice().reverse().map((x) => [esc(x.label), fmt1(x.value)]));

  const p = d.projects, e = d.evaluations;
  document.getElementById("work").innerHTML = `
    <div class="tiles">${tiles([[fmt(p.validated_90d), "proyectos validados (90 días)"], [fmt(e.done_90d), "evaluaciones hechas (90 días)"],
      [e.correction_points == null ? "–" : fmt(e.correction_points), "puntos de corrección"]])}</div>
    <h3 class="mt">En curso ahora</h3>
    ${p.in_progress.length ? `<ul class="list plain">${p.in_progress.map((x) => `<li class="proj"><div><span class="t">${esc(x.name)}</span> <span class="m">${x.days == null ? "" : `desde hace ${fmt(x.days)} días`}</span>`
        + (x.context ? `<div class="m">Lo habitual: validarlo en ${x.context.median_days == null ? "–" : fmt1(x.context.median_days)} días · lo valida el ${pct(x.context.validation_rate)} · nota media ${fmt1(x.context.avg_mark)}</div>` : "")
        + (x.help ? `<div class="m"><a href="/ayuda?project=${Number(x.id)}#recursos">${fmt(x.resources)} recursos</a> · <a href="/ayuda?project=${Number(x.id)}#mentoria">${fmt(x.mentors)} mentores</a> · <a href="/ayuda?project=${Number(x.id)}#pedir">Pedir ayuda</a></div>` : "")
        + `</div></li>`).join("")}</ul>`
      : `<p class="sub">No tienes proyectos en curso.</p>`}`;

  renderHabits(d.habits);
  const sr = d.self_reported || {};
  document.getElementById("deadline").value = sr.deadline || "";
  document.getElementById("freeze").value = sr.freeze_until || "";
  document.getElementById("bh-note").textContent = d.blackhole_api ? ` Fecha de blackhole según la API: ${d.blackhole_api}.` : "";
}

function renderHabits(hb) {
  const card = document.getElementById("habits-card");
  card.hidden = !hb;
  if (!hb) return;
  const short = ["Más lento", "Medio-lento", "Medio-rápido", "Más rápido"];
  const mine = hb.mine ? hb.mine.quartile : null;
  columns(document.getElementById("habits-chart"), hb.quartiles.map((q, i) => ({ label: short[i], full: q.label, value: q.median_hours_30d, hi: i === mine })), {
    labelEvery: 1, tip: (x) => `${esc(x.full)}: mediana <b>${fmt1(x.value)} h</b> en 30 días`,
  });
  document.getElementById("habits-sub").textContent = (hb.mine
    ? `Estás en el grupo «${hb.quartiles[hb.mine.quartile].label.toLowerCase()}» de ${fmt(hb.students)} alumnos y llevas ${fmt1(hb.mine.hours_30d)} h en 30 días. `
    : "") + "Es una correlación entre horas y ritmo: no demuestra que más horas den más nivel, pero sirve de referencia.";
}

function loadMe() {
  return fetch("/api/me").then(async (r) => {
    if (r.status === 401) { location.replace("/login"); return; }
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.status);
    renderMe(d);
  }).catch((e) => {
    document.getElementById("me-sub").textContent = `No se pudo cargar tu panel (${e.message}). Inténtalo de nuevo en unos minutos.`;
  });
}

async function saveSelf(deadline, freeze) {
  const msg = document.getElementById("self-msg");
  msg.textContent = "Guardando…";
  try {
    const r = await fetch("/api/me/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deadline: deadline || null, freeze_until: freeze || null }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `error ${r.status}`);
    await loadMe();
    msg.textContent = deadline || freeze ? "Guardado." : "Borrado.";
  } catch (e) {
    msg.textContent = `No se pudo guardar: ${e.message}`;
  }
}
document.getElementById("self-form").addEventListener("submit", (e) => {
  e.preventDefault();
  saveSelf(document.getElementById("deadline").value, document.getElementById("freeze").value);
});
document.getElementById("self-clear").addEventListener("click", () => saveSelf("", ""));
document.getElementById("erase").addEventListener("click", async () => {
  if (!confirm("Se borrará todo lo que guardamos de ti en esta web y se cerrará tu sesión. ¿Seguro?")) return;
  const msg = document.getElementById("erase-msg");
  try {
    const r = await fetch("/api/me/delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (!r.ok) throw new Error(`error ${r.status}`);
    location.replace("/");
  } catch (e) { msg.textContent = `No se pudo borrar: ${e.message}`; }
});
loadMe();
