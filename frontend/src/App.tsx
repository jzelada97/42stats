import { lazy, Suspense } from "react";
import { pageTitle } from "./lib/brand";

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
  login: pageTitle("Entrar con 42"),
  me: pageTitle("Mi panel"),
  ayuda: pageTitle("Ayuda entre alumnos"),
  campus: pageTitle("Estadísticas del campus"),
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
