"use strict";

const ERRORS = {
  denegado: "Cancelaste el acceso en 42. Puedes volver a intentarlo cuando quieras.",
  estado: "La sesión de acceso caducó o no es válida. Vuelve a pulsar «Entrar con 42».",
  intercambio: "42 no confirmó tu acceso. Inténtalo de nuevo en un minuto.",
  "fuera-de-campus": "Tu cuenta no está en los datos del campus de Madrid, así que no hay panel que mostrar.",
};

const code = new URLSearchParams(location.search).get("error");
if (code) {
  const box = document.getElementById("error");
  box.textContent = ERRORS[code] || "No se pudo completar el acceso.";
  box.hidden = false;
}

fetch("/api/session").then((r) => r.json()).then((u) => {
  if (u.logged_in) location.replace("/me");
  if (!u.login_enabled) {
    document.getElementById("disabled").hidden = false;
    const b = document.getElementById("login-btn");
    b.setAttribute("aria-disabled", "true");
    b.removeAttribute("href");
  }
}).catch(() => {});

fetch("/api/overview").then((r) => r.ok ? r.json() : Promise.reject()).then((o) => {
  const nf = new Intl.NumberFormat("es-ES");
  const tile = (v, l) => `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`;
  document.getElementById("teaser-tiles").innerHTML = tile(nf.format(o.cursus_current), "alumnos con el 42cursus abierto")
    + tile(o.avg_level == null ? "–" : nf.format(o.avg_level), "nivel medio") + tile(nf.format(o.students), "alumnos registrados");
  document.getElementById("teaser").hidden = false;
}).catch(() => {});
