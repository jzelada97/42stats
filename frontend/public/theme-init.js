/* Aplica el tema guardado antes de pintar (sin parpadeo). Va como fichero propio porque el CSP no admite scripts en línea. */
(function () {
  try {
    var m = localStorage.getItem("theme");
    if (m === "light" || m === "dark") document.documentElement.setAttribute("data-theme", m);
  } catch (e) { /* sin almacenamiento: tema automático */ }
})();
