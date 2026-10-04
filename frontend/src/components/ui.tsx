import type { ReactNode } from "react";
import { fmt } from "../lib/format";

export function Section({ id, kicker, title, lead, children }: { id?: string; kicker?: string; title: string; lead?: ReactNode; children?: ReactNode }) {
  const hid = id ? `h-${id}` : undefined;
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
