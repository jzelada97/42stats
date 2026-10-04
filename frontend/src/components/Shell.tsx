import { useEffect, useState, type ReactNode } from "react";
import { get, useSession } from "../lib/api";
import { useTheme, type Mode } from "../lib/theme";
import { TooltipProvider } from "../lib/tooltip";

export interface NavLink {
  href: string;
  label: string;
  /** Marca la entrada de Ayuda con el número de cosas pendientes. */
  badge?: boolean;
}

const ICONS: Record<Mode, ReactNode> = {
  auto: <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M12 4v16" /><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" /></svg>,
  light: <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" /></svg>,
  dark: <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" /></svg>,
};
const LABEL: Record<Mode, string> = { auto: "Auto", light: "Claro", dark: "Oscuro" };

export function ThemeToggle() {
  const [mode, cycle] = useTheme();
  return (
    <button type="button" className="theme-btn" onClick={cycle} aria-label={`Tema: ${LABEL[mode]}. Pulsa para cambiar`} title="Cambiar tema">
      {ICONS[mode]}<span>{LABEL[mode]}</span>
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

export function Header({ sub, links, current, showAuth = true }: { sub: string; links: NavLink[]; current?: string; showAuth?: boolean }) {
  const session = useSession();
  const badge = useHelpBadge(!!session?.logged_in);
  return (
    <header className="bar">
      <div className="bar-in">
        <a className="brand" href="/">
          <svg className="mark" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M12 3v18M8 9h8M8 15h8" />
          </svg>
          42 Madrid<small>/ {sub}</small>
        </a>
        <nav className="nav" aria-label="Secciones">
          {links.map((l) => (
            <a key={l.href} href={l.href} aria-current={current === l.href ? "true" : undefined}>
              {l.label}
              {l.badge && badge > 0 && <span className="badge" title="Cosas esperándote en Ayuda">{badge}</span>}
            </a>
          ))}
        </nav>
        {showAuth && session && (session.logged_in
          ? <a className="auth-link" href="/me">Mi panel · {session.name || session.login}</a>
          : <a className="auth-link" href="/login">Entrar con 42</a>)}
        <ThemeToggle />
      </div>
    </header>
  );
}

export function Shell({ sub, links, current, children, foot, showAuth = true }: { sub: string; links: NavLink[]; current?: string; children: ReactNode; foot?: ReactNode; showAuth?: boolean }) {
  return (
    <TooltipProvider>
      <Header sub={sub} links={links} current={current} showAuth={showAuth} />
      {children}
      {foot && <footer className="foot">{foot}</footer>}
    </TooltipProvider>
  );
}

/** Resalta en la barra la sección visible mientras se hace scroll. */
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
