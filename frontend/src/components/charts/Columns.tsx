import type { ReactNode } from "react";
import { fmt } from "../../lib/format";
import { useTip } from "../../lib/tooltip";
import { useWidth } from "../../lib/useWidth";

export interface Bar {
  label: string;
  value: number;
  hi?: boolean;
  [extra: string]: any;
}

export function niceMax(v: number): number {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

export interface Margin {
  l: number;
  r: number;
  t: number;
  b: number;
}

/** Marco de un gráfico de ejes: rejilla fina, ticks redondos y línea base. */
export function Axes({ w, m, ih, max }: { w: number; m: Margin; ih: number; max: number }) {
  const y = (v: number) => m.t + ih - (v / max) * ih;
  const ticks = max <= 4 ? Math.max(1, Math.round(max)) : 4;
  return (
    <>
      {Array.from({ length: ticks + 1 }, (_, i) => {
        const v = (max / ticks) * i;
        return (
          <g key={i}>
            <line className={i ? "grid" : "axis"} x1={m.l} x2={w - m.r} y1={y(v)} y2={y(v)} />
            <text x={m.l - 8} y={y(v) + 4} textAnchor="end">{fmt(Math.round(v * 10) / 10)}</text>
          </g>
        );
      })}
    </>
  );
}

interface Props {
  data: Bar[];
  tip?: (d: Bar) => ReactNode;
  labelEvery?: number;
  label: string;
}

/** Columnas finas (máx. 24 px) con el extremo redondeado; etiqueta solo en el máximo. */
export function Columns({ data, tip, labelEvery, label }: Props) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const { show, hide } = useTip();
  return (
    <div className="chart" ref={ref}>
      {w > 0 && data.length > 0 && <ColumnsSvg w={w} data={data} tip={tip} labelEvery={labelEvery} label={label} show={show} hide={hide} />}
    </div>
  );
}

function ColumnsSvg({ w, data, tip, labelEvery, label, show, hide }: Props & { w: number; show: ReturnType<typeof useTip>["show"]; hide: () => void }) {
  const h = 240;
  const m: Margin = { l: 44, r: 8, t: 18, b: 28 };
  const max = niceMax(Math.max(...data.map((d) => d.value)));
  const iw = w - m.l - m.r;
  const ih = h - m.t - m.b;
  const y = (v: number) => m.t + ih - (v / max) * ih;
  const band = iw / data.length;
  const bw = Math.min(24, band * 0.6);
  const step = labelEvery || Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(iw / 58))));
  const top = data.reduce((a, d, i) => (d.value > data[a].value ? i : a), 0);
  const anyHi = data.some((d) => d.hi);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label={label}>
      <Axes w={w} m={m} ih={ih} max={max} />
      {data.map((d, i) => {
        const x = m.l + band * i + (band - bw) / 2;
        const yt = y(d.value);
        const hh = Math.max(m.t + ih - yt, 0);
        const r = Math.min(4, hh, bw / 2);
        return (
          <g key={i}>
            {hh > 0 && (
              <path className={d.hi ? "bar hi" : "bar"}
                d={`M${x},${m.t + ih} V${yt + r} Q${x},${yt} ${x + r},${yt} H${x + bw - r} Q${x + bw},${yt} ${x + bw},${yt + r} V${m.t + ih} Z`} />
            )}
            {d.hi && <text className="lbl" x={x + bw / 2} y={yt - 6} textAnchor="middle">tú</text>}
            {!d.hi && i === top && d.value > 0 && !anyHi && <text className="lbl" x={x + bw / 2} y={yt - 6} textAnchor="middle">{fmt(d.value)}</text>}
            {i % step === 0 && <text x={x + bw / 2} y={h - 8} textAnchor="middle">{d.label}</text>}
            <rect className="hit" x={m.l + band * i} y={m.t} width={band} height={ih}
              onPointerMove={(e) => show(e, tip ? tip(d) : <>{d.label}: <b>{fmt(d.value)}</b></>)} onPointerLeave={hide} />
          </g>
        );
      })}
    </svg>
  );
}
