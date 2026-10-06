import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { get, useSession } from "../lib/api";
import { BRAND } from "../lib/brand";
import { useTheme, type Mode } from "../lib/theme";
import { TooltipProvider } from "../lib/tooltip";
import { Seigaiha } from "./charts/Decor";

export interface NavLink {
  href: string;
  label: string;
  /** Marca la entrada de Ayuda con el número de cosas pendientes. */
  badge?: boolean;
}

/** Las páginas de la web: siempre las mismas, en el menú. Cada página solo añade sus propias secciones. */
export const PAGES: NavLink[] = [
  { href: "/me", label: "Mi panel" },
  { href: "/ayuda", label: "Ayuda entre alumnos", badge: true },
  { href: "/campus", label: "Estadísticas del campus" },
];

const ICONS: Record<Mode, ReactNode> = {
  auto: <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M12 4v16" /><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" /></svg>,
  light: <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" /></svg>,
  dark: <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" /></svg>,
};
const LABEL: Record<Mode, string> = { auto: "Auto", light: "Claro", dark: "Oscuro" };

export function ThemeToggle({ className = "theme-btn" }: { className?: string }) {
  const [mode, cycle] = useTheme();
  return (
    <button type="button" className={className} onClick={cycle} aria-label={`Tema: ${LABEL[mode]}. Pulsa para cambiar`} title="Cambiar tema">
      {ICONS[mode]}<span>Tema: {LABEL[mode]}</span>
    </button>
  );
}

/** Cosas esperándote en Ayuda: peticiones por responder, mentores que se ofrecieron y confirmaciones pendientes. */
export const HELP_CHANGED = "help-changed";
function useHelpBadge(enabled: boolean): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const load = () => get<{ total: number }>("/api/help/summary").then((s) => setN(s.total)).catch(() => undefined);
    void load();
    window.addEventListener(HELP_CHANGED, load);                    // Ayuda avisa cuando algo cambia (te ofreciste, cerraste...)
    return () => window.removeEventListener(HELP_CHANGED, load);
  }, [enabled]);
  return n;
}

function Burger({ open }: { open: boolean }) {
  return (
    <svg className="burger" data-open={open ? "1" : "0"} viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <line className="l1" x1="4" y1="7" x2="20" y2="7" />
      <line className="l2" x1="4" y1="12" x2="20" y2="12" />
      <line className="l3" x1="4" y1="17" x2="20" y2="17" />
    </svg>
  );
}

/** Menú desplegable: se cierra con Escape, al pulsar fuera o al elegir una opción, y devuelve el foco al botón. */
function Menu({ sub, sections, current, badge, session }: {
  sub: string; sections: NavLink[]; current?: string; badge: number; session: { login: string | null; name: string | null };
}) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) btn.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("a, button")?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(true); };
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!panel.current?.contains(t) && !btn.current?.contains(t)) close(false);
    };
    document.addEventListener("keydown", key);
    document.addEventListener("pointerdown", away);
    return () => { document.removeEventListener("keydown", key); document.removeEventListener("pointerdown", away); };
  }, [open, close]);

  const here = location.pathname.replace(/\/+$/, "");
  return (
    <div className="menu-wrap">
      <button ref={btn} type="button" className="menu-btn" aria-label="Menú" aria-haspopup="true" aria-expanded={open} aria-controls="site-menu"
        onClick={() => setOpen((o) => !o)}>
        <Burger open={open} />
        {badge > 0 && !open && <span className="dot" aria-label={`${badge} pendientes en Ayuda`} />}
      </button>
      {open && (
        <nav id="site-menu" className="menu" aria-label="Navegación" ref={panel}>
          <a className="brand menu-brand" href="/">{BRAND}<small>/ {sub}</small></a>
          <div className="who">Hola, <b>{session.name || session.login}</b></div>
          <ul className="menu-group">
            {PAGES.map((l) => (
              <li key={l.href}>
                <a href={l.href} aria-current={here === l.href ? "page" : undefined} onClick={() => close(false)}>
                  {l.label}
                  {l.badge && badge > 0 && <span className="badge" title="Cosas esperándote en Ayuda">{badge}</span>}
                </a>
              </li>
            ))}
          </ul>
          {sections.length > 0 && (
            <>
              <div className="menu-title">En esta página</div>
              <ul className="menu-group">
                {sections.map((l) => (
                  <li key={l.href}>
                    <a href={l.href} aria-current={current === l.href ? "true" : undefined} onClick={() => close(false)}>
                      {l.label}
                      {l.badge && badge > 0 && <span className="badge">{badge}</span>}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="menu-foot">
            <ThemeToggle className="menu-item" />
            <a className="menu-item" href="/auth/logout">Salir</a>
          </div>
        </nav>
      )}
    </div>
  );
}

/** Sin barra: con sesión solo flota el botón de las tres rayas (el nombre y la navegación van dentro del menú); sin sesión, el nombre y el tema. */
export function Header({ sub, links, current, showAuth = true }: { sub: string; links: NavLink[]; current?: string; showAuth?: boolean }) {
  const session = useSession();
  const badge = useHelpBadge(!!session?.logged_in);
  if (session?.logged_in) {
    return <div className="float-menu"><div className="float-in"><Menu sub={sub} sections={links} current={current} badge={badge} session={session} /></div></div>;
  }
  return (
    <div className="float-bare">
      <div className="float-in spread">
        <a className="brand" href="/">{BRAND}<small>/ {sub}</small></a>
        <div className="bar-actions">
          {showAuth && session && <a className="auth-link" href="/login">Entrar con 42</a>}
          <ThemeToggle />
        </div>
      </div>
    </div>
  );
}

/** Otra app del autor, al pie de todas las páginas. El logo se sirve desde esta misma web (la CSP no deja cargar imágenes de fuera). */
function KonjoNote() {
  return (
    <aside className="konjo">
      <a className="konjo-link" href="https://konjo.com.es" target="_blank" rel="noopener noreferrer">
        <span className="konjo-line">Prueba Konjō</span>
        <img src="/static/konjo.png" alt="" width="44" height="44" />
      </a>
    </aside>
  );
}

export function Shell({ sub, links, current, children, foot, showAuth = true }: { sub: string; links: NavLink[]; current?: string; children: ReactNode; foot?: ReactNode; showAuth?: boolean }) {
  return (
    <TooltipProvider>
      <div className="side-decor left" aria-hidden="true"><Seigaiha /></div>
      <div className="side-decor right" aria-hidden="true"><Seigaiha /></div>
      <Header sub={sub} links={links} current={current} showAuth={showAuth} />
      {children}
      {foot && <footer className="foot">{foot}</footer>}
      <KonjoNote />
    </TooltipProvider>
  );
}

/** Resalta en el menú la sección visible mientras se hace scroll. */
export function useActiveSection(ids: string[]): string | undefined {
  const [active, setActive] = useState<string>();
  useEffect(() => {
    const els = ids.map((id) => document.getElementById(id)).filter((e): e is HTMLElement => !!e);
    const io = new IntersectionObserver(
      (entries) => entries.forEach((en) => { if (en.isIntersecting) setActive("#" + en.target.id); }),
      { rootMargin: "-30% 0px -60% 0px" },
    );
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [ids]);
  return active;
}
