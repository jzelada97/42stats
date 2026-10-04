"use strict";

const ERRORS = {
  denegado: "Cancelaste el acceso en 42. Puedes volver a intentarlo cuando quieras.",
  estado: "El acceso no se pudo completar (caducó, se repitió o tu navegador bloquea las cookies). Vuelve a pulsar «Entrar con 42» una sola vez y sin abrir otra pestaña.",
  intercambio: "42 no confirmó tu acceso. Inténtalo de nuevo en un minuto.",
  limite: "Demasiados intentos seguidos. Espera un minuto y vuelve a probar.",
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
