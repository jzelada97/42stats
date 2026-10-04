import { useState, type ReactNode } from "react";
import { fmt } from "../../lib/format";
import { useTip } from "../../lib/tooltip";
import { useWidth } from "../../lib/useWidth";
import { Axes, niceMax, type Margin } from "./Columns";

export interface Point {
  label: string;
  value: number;
  [extra: string]: any;
}

interface Props {
  data: Point[];
  tip?: (d: Point) => ReactNode;
  xlabel?: (d: Point) => string;
  label: string;
}

/** Línea de 2 px con relleno suave, punto final y cruz con tooltip. */
export function LineChart({ data, tip, xlabel, label }: Props) {
  const [ref, w] = useWidth<HTMLDivElement>();
  return <div className="chart" ref={ref}>{w > 0 && data.length > 0 && <LineSvg w={w} data={data} tip={tip} xlabel={xlabel} label={label} />}</div>;
}

function LineSvg({ w, data, tip, xlabel, label }: Props & { w: number }) {
  const { show, hide } = useTip();
  const [hover, setHover] = useState<number | null>(null);
  const h = 240;
  const m: Margin = { l: 44, r: 14, t: 18, b: 28 };
  const max = niceMax(Math.max(...data.map((d) => d.value)));
  const iw = w - m.l - m.r;
  const ih = h - m.t - m.b;
  const y = (v: number) => m.t + ih - (v / max) * ih;
  const x = (i: number) => m.l + (data.length === 1 ? iw / 2 : (iw * i) / (data.length - 1));
  const last = data.length - 1;
  const pts = data.map((d, i) => `${x(i)},${y(d.value)}`);
  const step = Math.ceil(data.length / Math.max(2, Math.floor(iw / 64)));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label={label}>
      <Axes w={w} m={m} ih={ih} max={max} />
      {data.map((d, i) => i % step === 0 && <text key={i} x={x(i)} y={h - 8} textAnchor="middle">{xlabel ? xlabel(d) : d.label}</text>)}
      <path className="area" d={`M${x(0)},${y(0)} L${pts.join(" L")} L${x(last)},${y(0)} Z`} />
      <polyline className="line" points={pts.join(" ")} />
      <circle className="dot" cx={x(last)} cy={y(data[last].value)} r={4} />
      {hover !== null && (
        <>
          <line className="cross" x1={x(hover)} x2={x(hover)} y1={m.t} y2={m.t + ih} />
          <circle className="dot" cx={x(hover)} cy={y(data[hover].value)} r={4} />
        </>
      )}
      <rect className="hit" x={m.l} y={m.t} width={iw} height={ih}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const i = Math.max(0, Math.min(last, Math.round(((e.clientX - r.left) / r.width) * last)));
          setHover(i);
          show(e, tip ? tip(data[i]) : <>{data[i].label}: <b>{fmt(data[i].value)}</b></>);
        }}
        onPointerLeave={() => { setHover(null); hide(); }} />
    </svg>
  );
}
