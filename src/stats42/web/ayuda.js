"use strict";

/* Toda cadena que viene de otros alumnos se pinta con textContent (h()), nunca como HTML. Los enlaces pasan por safeUrl(). */

const state = { overview: null, resources: null, rank: undefined, chosen: new Set() };

function h(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "href") { const u = props.external ? safeUrl(v) : profileOrPath(v); if (u) e.href = u; }
    else if (k === "external") { e.target = "_blank"; e.rel = "noopener noreferrer nofollow"; }
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) e.append(kid && kid.nodeType ? kid : document.createTextNode(kid ?? ""));
  return e;
}
const profileOrPath = (v) => (typeof v === "string" && v.startsWith("/") && !v.startsWith("//") ? v : safeUrl(v));
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
const setMsg = (id, text) => { document.getElementById(id).textContent = text; };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.status === 401) { location.replace("/login"); throw new Error("sesión necesaria"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : (Array.isArray(data.detail) ? "Revisa los campos del formulario." : `error ${r.status}`));
  return data;
}

const wantedProject = (() => { const v = Number(new URLSearchParams(location.search).get("project")); return Number.isInteger(v) && v > 0 ? v : null; })();

function fillSelect(sel, items, { general = false, only = null, selected = null } = {}) {
  clear(sel);
  if (general) sel.append(h("option", { value: "" }, "General (todo el círculo)"));
  for (const it of items) if (!only || only.has(it.id)) sel.append(h("option", { value: String(it.id) }, it.name));
  if (selected != null && [...sel.options].some((o) => o.value === String(selected))) sel.value = String(selected);
}

/* Círculo activo: todos los desplegables de proyectos solo muestran los de ese círculo (null = "Sin rank"). */
const inRank = (p) => p.rank === state.rank;
const projectsHere = () => state.overview.projects.filter(inRank);

function renderRankSelect() {
  const sel = clear(document.getElementById("rank-select"));
  for (const r of state.overview.ranks) sel.append(h("option", { value: r.id == null ? "none" : String(r.id) }, r.name + " (" + Number(r.projects) + ")"));
  sel.value = state.rank == null ? "none" : String(state.rank);
}
document.getElementById("rank-select").addEventListener("change", (e) => {
  state.rank = e.target.value === "none" ? null : Number(e.target.value);
  renderRank().catch(() => {});
});

async function renderRank() {
  const o = state.overview;
  const here = projectsHere();
  const unvalidated = new Set(here.filter((p) => !o.validated.some((v) => v.id === p.id)).map((p) => p.id));
  const keep = (id) => Number(document.getElementById(id).value) || wantedProject;
  renderRankSelect();
  fillSelect(document.getElementById("res-project"), here, { general: true, selected: keep("res-project") });
  fillSelect(document.getElementById("rf-project"), here, { general: true, selected: wantedProject });
  fillSelect(document.getElementById("mentor-project"), here, { selected: keep("mentor-project") });
  fillSelect(document.getElementById("req-project"), here, { only: unvalidated, selected: wantedProject });
  renderOffer(o);
  await Promise.all([loadResources(), loadMentors()]);
}

/* ---------------------------------------------------------------- insignias de mentoría (dibujos, sin texto) */
const SVGNS = "http://www.w3.org/2000/svg";
const BADGE_PATHS = {
  Brote: ["M12 21v-8", "M12 13c0-4 3-6 7-6 0 4-3 6-7 6z", "M12 15c0-3-2-5-6-5 0 3 2 5 6 5z"],
  "Caña": ["M12 3v18", "M9.5 9h5", "M9.5 15h5", "M12 7c2-1 4-1 6 0", "M12 13c-2-1-4-1-6 0"],
  Bosque: ["M5 21V9", "M12 21V3", "M19 21V11", "M3.5 14h3 M10.5 9h3 M10.5 15h3 M17.5 16h3"],
};
function badge(tier) {
  if (!BADGE_PATHS[tier]) return "";
  const s = document.createElementNS(SVGNS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: "20", height: "20", class: "tier-badge", "aria-hidden": "true" })) s.setAttribute(k, v);
  for (const d of BADGE_PATHS[tier]) { const p = document.createElementNS(SVGNS, "path"); p.setAttribute("d", d); s.append(p); }
  return s;
}
const pts = (n) => n + (n === 1 ? " punto" : " puntos");

function renderPoints(p) {
  const box = document.getElementById("my-points");
  const any = p && (p.verified || p.pending);
  box.hidden = !any;
  if (!any) return;
  clear(box).append(
    h("div", { class: "row" }, badge(p.tier), h("b", {}, p.tier || "Aún sin tramo"), h("span", { class: "m" }, pts(p.verified) + (p.verified === 1 ? " verificado" : " verificados"))),
    p.pending ? h("div", { class: "m" }, p.pending + " pendientes: cuentan cuando quien te agradeció valide el proyecto.") : "",
    p.next ? h("div", { class: "m" }, "Te faltan " + p.next.needs + " para " + p.next.name + ".") : "");
}

/* ---------------------------------------------------------------- recursos */
async function loadResources() {
  const sel = document.getElementById("res-project");
  const pid = sel.value ? Number(sel.value) : null;
  const query = pid ? `?project_id=${pid}` : (state.rank != null ? "?rank=" + Number(state.rank) : "");
  const d = await api("/api/help/resources" + query);
  const ul = clear(document.getElementById("res-list"));
  if (!d.resources.length) ul.append(h("li", { class: "empty" }, "Aún no hay recursos aprobados para este proyecto. Propón el primero."));
  for (const r of d.resources) {
    ul.append(h("li", {},
      h("span", { class: "chip-kind" }, r.kind),
      h("div", {}, h("a", { href: r.url, external: "1", class: "t" }, r.title), h("div", { class: "m" }, r.project || "General")),
    ));
  }
  const pend = d.mine_pending;
  document.getElementById("res-pending-card").hidden = !pend.length;
  const pl = clear(document.getElementById("res-pending"));
  for (const r of pend) pl.append(h("li", {}, h("span", { class: "t" }, r.title), h("span", { class: "m" }, r.status === "pending" ? "pendiente de revisión" : "rechazado")));
}

document.getElementById("res-project").addEventListener("change", () => loadResources().catch(() => {}));
document.getElementById("res-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  setMsg("rf-msg", "Enviando…");
  try {
    const pid = document.getElementById("rf-project").value;
    await api("/api/help/resources", {
      project_id: pid ? Number(pid) : null, title: document.getElementById("rf-title").value, url: document.getElementById("rf-url").value,
      kind: document.getElementById("rf-kind").value, confirm_no_solution: document.getElementById("rf-confirm").checked,
    });
    setMsg("rf-msg", "Enviado: lo revisaremos antes de publicarlo.");
    document.getElementById("rf-title").value = ""; document.getElementById("rf-url").value = ""; document.getElementById("rf-confirm").checked = false;
    await loadResources();
    if (state.overview && state.overview.is_admin) await loadPending();
  } catch (err) { setMsg("rf-msg", err.message); }
});

/* ---------------------------------------------------------------- mentoría */
async function loadMentors() {
  const pid = Number(document.getElementById("mentor-project").value);
  const ul = clear(document.getElementById("mentor-list"));
  if (!pid) return;
  const d = await api(`/api/help/mentors?project_id=${pid}`);
  if (!d.mentors.length) ul.append(h("li", { class: "empty" }, "Nadie se ha ofrecido todavía en este proyecto."));
  for (const m of d.mentors) {
    const meta = [m.level != null ? `nivel ${m.level}` : null, m.mark != null ? `nota ${m.mark}` : null, m.validated_on ? `validado el ${m.validated_on}` : null].filter(Boolean).join(" · ");
    ul.append(h("li", {},
      h("div", {}, h("a", { href: profileUrl(m.login), external: "1", class: "t mono" }, m.login),
        m.tier ? h("div", { class: "tier", title: m.tier + " · " + pts(m.points) + (m.points === 1 ? " verificado" : " verificados") }, badge(m.tier), h("span", {}, m.tier)) : ""),
      h("div", {}, h("div", { class: "m" }, meta), m.note ? h("div", { class: "note" }, m.note) : ""),
    ));
  }
}
document.getElementById("mentor-project").addEventListener("change", () => loadMentors().catch(() => {}));

function renderOffer(o) {
  const box = document.getElementById("offer-projects");
  [...box.querySelectorAll("label, p")].forEach((l) => l.remove());
  const here = o.validated.filter((v) => v.in_help && inRank(v));
  const offerable = o.validated.filter((v) => v.in_help);
  if (!o.validated.length) box.append(h("p", { class: "sub" }, "Aún no tenemos proyectos validados tuyos. Cuando valides alguno podrás ofrecer ayuda."));
  else if (!here.length) box.append(h("p", { class: "sub" }, offerable.length ? "No tienes proyectos validados en este círculo. Cambia de círculo arriba para ver los demás." : "Ninguno de tus proyectos validados tiene sección de ayuda."));
  const hidden = offerable.length - here.length;
  for (const v of here) {
    const cb = h("input", { type: "checkbox", value: String(v.id), name: "offer-project" });
    cb.checked = state.chosen.has(v.id);
    cb.addEventListener("change", () => { if (cb.checked) state.chosen.add(v.id); else state.chosen.delete(v.id); });
    box.append(h("label", { class: "check" }, cb, " ", v.name, v.mark != null ? h("span", { class: "m" }, " (nota " + v.mark + ")") : ""));
  }
  if (hidden > 0 && here.length) box.append(h("p", { class: "sub" }, "Y " + hidden + " validados en otros círculos (lo que hayas elegido allí se conserva)."));
  document.getElementById("offer-note").value = o.offer ? o.offer.note : "";
  document.getElementById("offer-active").checked = o.offer ? o.offer.active : true;
}
document.getElementById("offer-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  setMsg("offer-msg", "Guardando…");
  try {
    const ids = [...state.chosen];
    await api("/api/help/offer", { active: document.getElementById("offer-active").checked, note: document.getElementById("offer-note").value, project_ids: ids });
    setMsg("offer-msg", "Guardado.");
    await refresh();
  } catch (err) { setMsg("offer-msg", err.message); }
});

/* ---------------------------------------------------------------- peticiones */
function requestItem(r, { closable }) {
  const li = h("li", {}, h("div", {},
    h("div", {}, h("span", { class: "t" }, r.project), r.login ? " · " : "", r.login ? h("a", { href: profileUrl(r.login), external: "1", class: "mono" }, r.login) : ""),
    h("p", { class: "note" }, r.message),
    h("div", { class: "m" }, [r.level != null ? `nivel ${r.level}` : null, `hace ${r.days_waiting ?? r.days ?? 0} días`].filter(Boolean).join(" · ")),
    r.mentors ? h("div", { class: "m" }, r.mentors.length ? "Mentores disponibles: " + r.mentors.map((m) => m.login).join(", ") : "Aún no hay mentores para este proyecto.") : "",
  ));
  if (closable) {
    const box = h("div", { class: "close-box" });
    let sel = null, cb = null, ck = null;
    if (r.mentors && r.mentors.length) {
      sel = h("select", { "aria-label": "¿Te ayudó alguien?" }, h("option", { value: "" }, "Cerrar sin agradecer"),
        r.mentors.map((m) => h("option", { value: m.login }, "Gracias a " + m.login)));
      cb = h("input", { type: "checkbox" });
      ck = h("label", { class: "check small" }, cb, " Me explicó, sin darme código");
      ck.hidden = true;
      sel.addEventListener("change", () => { ck.hidden = !sel.value; });
      box.append(sel, ck, h("p", { class: "m" }, "El punto del mentor cuenta cuando valides este proyecto."));
    }
    const b = h("button", { class: "btn small ghost", type: "button" }, "Cerrar");
    b.addEventListener("click", async () => {
      try {
        const res = await api(`/api/help/requests/${Number(r.id)}/close`, { helped_by: sel && sel.value ? sel.value : null, no_code: !!(cb && cb.checked) });
        await refresh();
        if (res.thanked) setMsg("req-msg", "Gracias enviado a " + res.thanked + ". Su punto cuenta cuando valides el proyecto.");
      } catch (e) { setMsg("req-msg", e.message); }
    });
    box.append(b);
    li.append(box);
  }
  return li;
}
function renderRequests(o) {
  renderPoints(o.points);
  const mine = clear(document.getElementById("my-requests"));
  if (!o.requests.length) mine.append(h("li", { class: "empty" }, "No tienes peticiones abiertas."));
  for (const r of o.requests) mine.append(requestItem(r, { closable: true }));
  const mentor = !!(o.offer && o.offer.active && o.offer.project_ids.length);
  document.getElementById("incoming-note").textContent = !mentor
    ? "Para ver las peticiones, ofrécete como mentor en un proyecto que ya hayas validado (arriba, en Mentoría)."
    : (o.incoming.length ? "" : "Ahora mismo nadie pide ayuda en tus proyectos.");
  const inc = clear(document.getElementById("incoming"));
  for (const r of o.incoming) inc.append(requestItem(r, { closable: false }));
}
document.getElementById("req-message").addEventListener("input", (e) => { document.getElementById("req-count").textContent = `${e.target.value.length} / 280`; });
document.getElementById("req-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  setMsg("req-msg", "Enviando…");
  try {
    const r = await api("/api/help/requests", { project_id: Number(document.getElementById("req-project").value), message: document.getElementById("req-message").value });
    document.getElementById("req-message").value = ""; document.getElementById("req-count").textContent = "0 / 280";
    setMsg("req-msg", r.mentors.length ? `Hecho. Hay ${r.mentors.length} mentor(es) para este proyecto: contáctalos desde su perfil.` : "Hecho. Aún no hay mentores en este proyecto; tu petición queda abierta.");
    await refresh();
  } catch (err) { setMsg("req-msg", err.message); }
});

/* ---------------------------------------------------------------- moderación */
/* El admin decide mirando el dominio real que abriría el navegador, no la cadena tal cual se escribió. */
const hostOf = (u) => { try { return new URL(u).hostname; } catch (_) { return "?"; } };

async function loadPending() {
  const d = await api("/api/admin/help/pending");
  const ul = clear(document.getElementById("pending-list"));
  if (!d.resources.length) ul.append(h("li", { class: "empty" }, "No hay nada pendiente."));
  for (const r of d.resources) {
    const li = h("li", {}, h("span", { class: "chip-kind" }, r.kind),
      h("div", {}, h("a", { href: r.url, external: "1", class: "t" }, r.title), h("div", { class: "m" }, `${r.project} · enviado por ${r.by}`), h("div", { class: "m mono" }, "destino: " + hostOf(r.url) + " · " + r.url)));
    for (const [action, label] of [["approve", "Aprobar"], ["reject", "Rechazar"]]) {
      const b = h("button", { class: action === "approve" ? "btn small" : "btn small ghost", type: "button" }, label);
      b.addEventListener("click", async () => { try { await api(`/api/admin/help/resources/${Number(r.id)}/${action}`, {}); await loadPending(); await loadResources(); } catch (e) { setMsg("mod-msg", e.message); } });
      li.append(b);
    }
    ul.append(li);
  }
}
const localTime = (iso) => { const d = new Date(iso); return isNaN(d) ? "?" : d.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }); };

async function loadLogins() {
  const d = await api("/api/admin/logins");
  const box = clear(document.getElementById("login-stats"));
  for (const [n, label] of [[d.day, "últimas 24 h"], [d.week, "7 días"], [d.month, "30 días"], [d.total, "en total"]]) {
    box.append(h("div", { class: "tile" }, h("div", { class: "v" }, String(Number(n))), h("div", { class: "l" }, label)));
  }
  const ul = clear(document.getElementById("login-list"));
  if (!d.recent.length) ul.append(h("li", { class: "empty" }, "Todavía no ha entrado nadie desde que existe este registro."));
  for (const e of d.recent) {
    ul.append(h("li", {}, h("span", { class: "t mono" }, e.login), h("span", { class: "m" }, "último acceso " + localTime(e.last) + " · " + Number(e.logins) + (e.logins === 1 ? " vez" : " veces"))));
  }
}

async function loadAbuse() {
  const d = await api("/api/admin/help/abuse");
  const ul = clear(document.getElementById("abuse-list"));
  if (!d.events.length) ul.append(h("li", { class: "empty" }, "Nadie ha chocado con un límite."));
  for (const e of d.events) {
    ul.append(h("li", {}, h("span", { class: "t mono" }, e.login), h("span", { class: "m" }, e.kind + " · " + Number(e.hits) + " golpes · último " + localTime(e.last))));
  }
}
/* ---------------------------------------------------------------- arranque */
async function refresh() {
  const o = await api("/api/help/overview");
  state.overview = o;
  state.chosen = new Set(o.offer ? o.offer.project_ids : []);
  if (state.rank === undefined || !o.ranks.some((r) => r.id === state.rank)) {      // primera carga: el del proyecto enlazado, el de tu proyecto en curso o el primero
    const linked = o.projects.find((p) => p.id === wantedProject);
    const mine = o.ranks.some((r) => r.id === o.default_rank) ? o.default_rank : (o.ranks[0] ? o.ranks[0].id : null);
    state.rank = linked ? linked.rank : mine;
  }
  renderRequests(o);
  document.getElementById("moderacion").hidden = !o.is_admin;
  await Promise.all([renderRank(), o.is_admin ? loadPending() : null, o.is_admin ? loadAbuse() : null, o.is_admin ? loadLogins() : null]);
}

refresh().catch((e) => { document.getElementById("h-ayuda").textContent = `No se pudo cargar la sección de ayuda (${e.message}).`; });
