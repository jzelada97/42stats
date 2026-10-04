import { useEffect, useId, useState, type ReactNode } from "react";

/** Olas seigaiha muy tenues: solo adorno (aria-hidden), nunca detrás de texto largo. */
export function Seigaiha({ className = "seigaiha" }: { className?: string }) {
  const id = useId();
  return (
    <svg className={className} aria-hidden="true" focusable="false">
      <defs>
        <pattern id={id} width="32" height="16" patternUnits="userSpaceOnUse">
          <g fill="none" stroke="currentColor" strokeWidth="1">
            {[0, 16, 32].flatMap((cx, k) => {
              const cy = k === 1 ? 16 : 8;
              return [13, 9, 5, 1.5].map((r) => <circle key={`${k}-${r}`} cx={cx} cy={cy} r={r} />);
            })}
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}

const point = (r: number, a: number): [number, number] => [50 + r * Math.sin(a), 50 - r * Math.cos(a)];
function arc(r: number, from: number, to: number): string {
  const [x0, y0] = point(r, from);
  const [x1, y1] = point(r, to);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${to - from > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

/** Ensō: un círculo abierto que se completa con el progreso (0 a 1). Dos trazos de distinto grosor imitan el pincel. */
export function Enso({ value, label, caption, tone, size = 132 }: { value: number; label: ReactNode; caption?: string; tone?: "warn"; size?: number }) {
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const [on, setOn] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setOn(true));
    return () => cancelAnimationFrame(t);
  }, []);
  const start = 0.18;
  const end = start + 5.75 * v;                                   // nunca se cierra del todo: es la gracia del ensō
  const anim = { strokeDasharray: 1, strokeDashoffset: on ? 0 : 1, transition: "stroke-dashoffset 900ms cubic-bezier(.22,.61,.36,1)" } as const;
  const color = tone === "warn" ? { stroke: "var(--hi)" } : undefined;
  return (
    <svg className="enso" viewBox="0 0 100 100" width={size} height={size} role="img" aria-label={typeof label === "string" ? `${label}${caption ? `, ${caption}` : ""}` : caption}>
      <path className="track" d={arc(36, start, start + 5.75)} />
      {v > 0.005 && <path className="brush" d={arc(36, start, end)} pathLength={1} strokeWidth={7} style={{ ...anim, ...color }} />}
      {v > 0.03 && <path className="brush thin" d={arc(38.4, start + 0.12, Math.max(start + 0.2, end - 0.1))} pathLength={1} strokeWidth={2.4} style={{ ...anim, ...color }} />}
      <text x="50" y={caption ? 51 : 56} textAnchor="middle">{label}</text>
      {caption && <text className="caption" x="50" y="65" textAnchor="middle">{caption}</text>}
    </svg>
  );
}

/** Insignia de mentoría dibujada con trazos (sin texto): brote, caña y bosque. */
const BADGES: Record<string, string[]> = {
  Brote: ["M12 21v-8", "M12 13c0-4 3-6 7-6 0 4-3 6-7 6z", "M12 15c0-3-2-5-6-5 0 3 2 5 6 5z"],
  "Caña": ["M12 3v18", "M9.5 9h5", "M9.5 15h5", "M12 7c2-1 4-1 6 0", "M12 13c-2-1-4-1-6 0"],
  Bosque: ["M5 21V9", "M12 21V3", "M19 21V11", "M3.5 14h3 M10.5 9h3 M10.5 15h3 M17.5 16h3"],
};
export function TierBadge({ tier }: { tier: string | null | undefined }) {
  if (!tier || !BADGES[tier]) return null;
  return (
    <svg className="tier-badge" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      {BADGES[tier].map((d) => <path key={d} d={d} />)}
    </svg>
  );
}
