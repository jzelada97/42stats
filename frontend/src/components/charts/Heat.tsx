import { DAYS, fmt, fmt1 } from "../../lib/format";
import { useTip } from "../../lib/tooltip";
import { useWidth } from "../../lib/useWidth";

const heat = (v: number, max: number): string =>
  `color-mix(in srgb, var(--accent) ${v > 0 ? 8 + 92 * Math.min(1, v / max) : 5}%, var(--surface))`;

export interface HeatCell {
  weekday: number;
  hour: number;
  value: number;
}

/** Mapa de calor día de la semana × hora. */
export function Heatmap({ cells }: { cells: HeatCell[] }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const { show, hide } = useTip();
  const L = 34;
  const T = 18;
  const cw = (w - L) / 24;
  const ch = Math.max(18, Math.min(30, cw));
  const h = T + ch * 7;
  const max = Math.max(...cells.map((c) => c.value), 0.1);
  return (
    <div className="chart" ref={ref}>
      {w > 0 && (
        <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label="Puestos ocupados por día de la semana y hora">
          {Array.from({ length: 8 }, (_, i) => i * 3).map((hr) => (
            <text key={hr} x={L + cw * hr + cw / 2} y={11} textAnchor="middle">{String(hr).padStart(2, "0")}</text>
          ))}
          {DAYS.map((d, i) => <text key={d} x={L - 8} y={T + ch * i + ch / 2 + 4} textAnchor="end">{d}</text>)}
          {cells.map((c) => (
            <rect key={`${c.weekday}-${c.hour}`} className="cell" x={L + cw * c.hour} y={T + ch * c.weekday} width={cw} height={ch}
              style={{ fill: heat(c.value, max) }}
              onPointerMove={(e) => show(e, <>{DAYS[c.weekday]} {String(c.hour).padStart(2, "0")}:00 · <b>{fmt1(c.value)}</b> puestos de media</>)}
              onPointerLeave={hide} />
          ))}
        </svg>
      )}
    </div>
  );
}

export interface Seat {
  cluster: number | string;
  row: number;
  seat: number;
  sessions: number;
}

/** Un panel por cluster: fila en vertical, puesto en horizontal (hosts tipo c3r5s1). */
export function SeatMap({ seats }: { seats: Seat[] }) {
  const { show, hide } = useTip();
  const max = Math.max(...seats.map((s) => s.sessions), 1);
  const byCluster = new Map<string, Seat[]>();
  for (const s of seats) byCluster.set(String(s.cluster), [...(byCluster.get(String(s.cluster)) ?? []), s]);
  const CW = 26;
  const CH = 16;
  const L = 26;
  const clusters = [...byCluster.keys()].sort((a, b) => Number(a) - Number(b));
  return (
    <div className="seatmap">
      {clusters.map((c) => {
        const list = byCluster.get(c)!;
        const rows = Math.max(...list.map((s) => s.row));
        const cols = Math.max(...list.map((s) => s.seat));
        const idx = new Map(list.map((s) => [`${s.row}-${s.seat}`, s.sessions]));
        return (
          <figure key={c}>
            <figcaption>cluster {c}</figcaption>
            <svg viewBox={`0 0 ${L + CW * cols} ${14 + CH * rows}`} width={L + CW * cols} height={14 + CH * rows} role="img" aria-label={`Cluster ${c}`}>
              {Array.from({ length: cols }, (_, i) => <text key={i} x={L + CW * i + CW / 2} y={9} textAnchor="middle">{i + 1}</text>)}
              {Array.from({ length: rows }, (_, r) => (
                <g key={r}>
                  <text x={L - 6} y={14 + CH * r + CH / 2 + 4} textAnchor="end">r{r + 1}</text>
                  {Array.from({ length: cols }, (_, s) => {
                    const n = idx.get(`${r + 1}-${s + 1}`) || 0;
                    return (
                      <rect key={s} className="cell" x={L + CW * s} y={14 + CH * r} width={CW} height={CH} style={{ fill: heat(n, max) }}
                        onPointerMove={(e) => show(e, <><span className="mono">c{c}r{r + 1}s{s + 1}</span> · <b>{fmt(n)}</b> sesiones</>)}
                        onPointerLeave={hide} />
                    );
                  })}
                </g>
              ))}
            </svg>
          </figure>
        );
      })}
    </div>
  );
}
