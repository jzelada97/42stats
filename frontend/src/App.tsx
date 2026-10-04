import { lazy, Suspense } from "react";

const Login = lazy(() => import("./pages/Login"));
const Me = lazy(() => import("./pages/Me"));
const Ayuda = lazy(() => import("./pages/Ayuda"));
const Campus = lazy(() => import("./pages/Campus"));

export type Route = "login" | "me" | "ayuda" | "campus";

/** Cada ruta del servidor sirve el mismo index.html: aquí se decide qué página pintar según la ruta. */
export function routeFor(pathname: string): Route {
  const p = pathname.replace(/\/+$/, "") || "/";
  if (p === "/me") return "me";
  if (p === "/ayuda") return "ayuda";
  if (p === "/campus") return "campus";
  return "login";
}

const TITLES: Record<Route, string> = {
  login: "Entrar con 42 · 42 Madrid",
  me: "Mi panel · 42 Madrid",
  ayuda: "Ayuda entre alumnos · 42 Madrid",
  campus: "Estadísticas del campus · 42 Madrid",
};

export default function App() {
  const route = routeFor(location.pathname);
  document.title = TITLES[route];
  return (
    <Suspense fallback={<div className="empty" role="status">Cargando…</div>}>
      {route === "me" ? <Me /> : route === "ayuda" ? <Ayuda /> : route === "campus" ? <Campus /> : <Login />}
    </Suspense>
  );
}
