"use strict";

/* Toda cadena que viene de otros alumnos se pinta con textContent (h()), nunca como HTML. Los enlaces pasan por safeUrl(). */

const state = { overview: null, resources: null };

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
  if (general) sel.append(h("option", { value: "" }, "General (todos los proyectos)"));
  for (const it of items) if (!only || only.has(it.id)) sel.append(h("option", { value: String(it.id) }, it.name));
  if (selected != null && [...sel.options].some((o) => o.value === String(selected))) sel.value = String(selected);
}

/* ---------------------------------------------------------------- recursos */
async function loadResources() {
  const sel = document.getElementById("res-project");
  const pid = sel.value ? Number(sel.value) : null;
  const d = await api("/api/help/resources" + (pid ? `?project_id=${pid}` : ""));
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
      h("a", { href: profileUrl(m.login), external: "1", class: "t mono" }, m.login),
      h("div", {}, h("div", { class: "m" }, meta), m.note ? h("div", { class: "note" }, m.note) : ""),
    ));
  }
}
document.getElementById("mentor-project").addEventListener("change", () => loadMentors().catch(() => {}));

function renderOffer(o) {
  const box = document.getElementById("offer-projects");
  [...box.querySelectorAll("label")].forEach((l) => l.remove());
  if (!o.validated.length) box.append(h("p", { class: "sub" }, "Aún no tenemos proyectos validados tuyos. Cuando valides alguno podrás ofrecer ayuda."));
  const chosen = new Set(o.offer ? o.offer.project_ids : []);
  for (const v of o.validated) {
    const cb = h("input", { type: "checkbox", value: String(v.id), name: "offer-project" });
    cb.checked = chosen.has(v.id);
    box.append(h("label", { class: "check" }, cb, " ", v.name, v.mark != null ? h("span", { class: "m" }, " (nota " + v.mark + ")") : ""));
  }
  document.getElementById("offer-note").value = o.offer ? o.offer.note : "";
  document.getElementById("offer-active").checked = o.offer ? o.offer.active : true;
}
document.getElementById("offer-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  setMsg("offer-msg", "Guardando…");
  try {
    const ids = [...document.querySelectorAll("#offer-projects input:checked")].map((i) => Number(i.value));
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
    const b = h("button", { class: "btn small ghost", type: "button" }, "Cerrar");
    b.addEventListener("click", async () => { try { await api(`/api/help/requests/${Number(r.id)}/close`, {}); await refresh(); } catch (e) { setMsg("req-msg", e.message); } });
    li.append(b);
  }
  return li;
}
function renderRequests(o) {
  const mine = clear(document.getElementById("my-requests"));
  if (!o.requests.length) mine.append(h("li", { class: "empty" }, "No tienes peticiones abiertas."));
  for (const r of o.requests) mine.append(requestItem(r, { closable: true }));
  document.getElementById("incoming-card").hidden = !o.incoming.length;
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
async function loadAbuse() {
  const d = await api("/api/admin/help/abuse");
  const ul = clear(document.getElementById("abuse-list"));
  if (!d.events.length) ul.append(h("li", { class: "empty" }, "Nadie ha chocado con un límite."));
  for (const e of d.events) {
    ul.append(h("li", {}, h("span", { class: "t mono" }, e.login), h("span", { class: "m" }, e.kind + " · " + Number(e.hits) + " golpes · último " + String(e.last || "").replace("T", " "))));
  }
}
/* ---------------------------------------------------------------- arranque */
async function refresh() {
  const o = await api("/api/help/overview");
  state.overview = o;
  const unvalidated = new Set(o.projects.filter((p) => !o.validated.some((v) => v.id === p.id)).map((p) => p.id));
  const sel = (id) => Number(document.getElementById(id).value) || wantedProject;
  fillSelect(document.getElementById("res-project"), o.projects, { general: true, selected: sel("res-project") });
  fillSelect(document.getElementById("rf-project"), o.projects, { general: true, selected: wantedProject });
  fillSelect(document.getElementById("mentor-project"), o.projects, { selected: sel("mentor-project") });
  fillSelect(document.getElementById("req-project"), o.projects, { only: unvalidated, selected: wantedProject });
  renderOffer(o);
  renderRequests(o);
  document.getElementById("moderacion").hidden = !o.is_admin;
  await Promise.all([loadResources(), loadMentors(), o.is_admin ? loadPending() : null, o.is_admin ? loadAbuse() : null]);
}

refresh().catch((e) => { document.getElementById("h-ayuda").textContent = `No se pudo cargar la sección de ayuda (${e.message}).`; });
