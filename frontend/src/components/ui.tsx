import { useEffect, useState, type ReactNode } from "react";
import { fmt } from "../lib/format";

const foldKey = (id: string) => `fold:${location.pathname}#${id}`;
function savedFold(id: string): boolean | null {
  try {
    const v = localStorage.getItem(foldKey(id));
    return v === null ? null : v === "1";
  } catch { return null; }
}

/** Una sección que se pliega. Un enlace con #id la abre; si el usuario la abre o cierra, se acuerda en este navegador. */
function Fold({ id, kicker, title, lead, open: initial, hint, children }: { id: string; kicker?: string; title: string; lead?: ReactNode; open: boolean; hint?: ReactNode; children?: ReactNode }) {
  const hid = `h-${id}`;
  const [open, setOpen] = useState(() => location.hash === `#${id}` || (savedFold(id) ?? initial));
  useEffect(() => {
    const on = () => { if (location.hash === `#${id}`) setOpen(true); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, [id]);
  return (
    <section className="section fold" id={id} aria-labelledby={hid}>
      <details open={open} onToggle={(e) => {
        const now = (e.currentTarget as HTMLDetailsElement).open;
        if (now === open) return;                               // el evento también salta al montar o al abrirse por un enlace: no es una elección del usuario
        setOpen(now);
        try { localStorage.setItem(foldKey(id), now ? "1" : "0"); } catch { /* sin almacenamiento: se queda como está */ }
      }}>
        <summary>
          <span className="fold-text">
            {kicker && <span className="kicker">{kicker}</span>}
            <h2 id={hid}>{title}</h2>
            {hint && !open && <span className="fold-hint">{hint}</span>}
          </span>
          <span className="fold-chev" aria-hidden="true" />
        </summary>
        <div className="fold-body">
          {lead && <p className="lead">{lead}</p>}
          {children}
        </div>
      </details>
    </section>
  );
}

/** `fold` la hace plegable: "open" o "closed" es cómo empieza; `hint` es el resumen que se ve mientras está cerrada. */
export function Section({ id, kicker, title, lead, fold, hint, children }: { id?: string; kicker?: string; title: string; lead?: ReactNode; fold?: "open" | "closed"; hint?: ReactNode; children?: ReactNode }) {
  const hid = id ? `h-${id}` : undefined;
  if (fold && id) return <Fold id={id} kicker={kicker} title={title} lead={lead} open={fold === "open"} hint={hint}>{children}</Fold>;
  return (
    <section className="section" id={id} aria-labelledby={hid}>
      <div className="section-head">
        {kicker && <div className="kicker">{kicker}</div>}
        <h2 id={hid}>{title}</h2>
        {lead && <p className="lead">{lead}</p>}
      </div>
      {children}
    </section>
  );
}

export function Card({ title, sub, raise, className = "", children }: { title?: ReactNode; sub?: ReactNode; raise?: boolean; className?: string; children?: ReactNode }) {
  return (
    <div className={`card${raise ? " raise" : ""}${className ? " " + className : ""}`}>
      {title && <h3>{title}</h3>}
      {sub && <p className="sub">{sub}</p>}
      {children}
    </div>
  );
}

export type TileItem = [value: ReactNode, label: ReactNode, unit?: string];
export function Tiles({ items }: { items: TileItem[] }) {
  return (
    <div className="tiles">
      {items.map(([v, l, unit], i) => (
        <div className="tile" key={i}>
          <div className="v">{v}{unit && <small>{unit}</small>}</div>
          <div className="l">{l}</div>
        </div>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export const WAITING = "Aún no hay datos: la carga inicial sigue en curso.";

export function DataTable({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="wrap">
      <table>
        <thead><tr>{head.map((h, i) => <th key={i} className={i ? "n" : ""}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j ? "n" : ""}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export function Disclosure({ summary = "Ver como tabla", children }: { summary?: string; children: ReactNode }) {
  return <details><summary>{summary}</summary>{children}</details>;
}

export function Meter({ value }: { value: number | null | undefined }) {
  if (value == null) return null;
  return <span className="meter"><i style={{ width: `${Math.round(value * 100)}%` }} /></span>;
}

export interface HRow {
  name: string;
  value: number;
  text?: ReactNode;
}
/** Barras horizontales (HTML, se adaptan solas al ancho). */
export function HBars({ rows }: { rows: HRow[] }) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="hbars">
      {rows.map((r, i) => (
        <div className="hrow" key={i}>
          <span className="name" title={r.name}>{r.name}</span>
          <span className="track"><i style={{ width: `${Math.max(1, (r.value / max) * 100)}%` }} /></span>
          <span className="val">{r.text ?? fmt(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** Carga con error visible: cada tarjeta explica qué pasó en vez de quedarse vacía. */
export function Failed({ message }: { message: string }) {
  return <Empty>No se pudieron cargar estos datos ({message}). Inténtalo de nuevo en unos minutos.</Empty>;
}
