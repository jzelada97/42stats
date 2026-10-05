import { useEffect, useId, useState, type CSSProperties, type ReactNode } from "react";

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

const smooth = (a: number, b: number, x: number) => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

const START = 0.42;                                              // el trazo arranca arriba a la derecha y gira en sentido horario
const SWEEP = 5.55;                                              // nunca se cierra del todo: la abertura es la gracia del ensō
/** Punto del centro del trazo a una fracción t (0 a 1) del recorrido: el radio deriva y tiembla un poco, como una mano. */
function centre(t: number): { x: number; y: number; nx: number; ny: number } {
  const a = START + SWEEP * t;
  const r = 34.5 + 3.4 * t + 0.9 * Math.sin(6.3 * t + 0.7) + 0.45 * Math.sin(15 * t + 2.1);
  return { x: 50 + r * Math.sin(a), y: 50 - r * Math.cos(a), nx: Math.sin(a), ny: -Math.cos(a) };
}

/** Grosor a lo largo del trazo (u de 0 a 1 en lo dibujado): se apoya con fuerza, aligera y termina en cola fina. */
const girth = (u: number, scale: number) =>
  scale * (1.2 + 7.2 * smooth(0, 0.05, u) - 3.4 * u + 0.7 * Math.sin(11 * u + 1.3)) * (1 - 0.8 * smooth(0.78, 1, u));

/** Contorno relleno del trazo hasta la fracción v del recorrido. */
function brushPath(v: number, scale = 1): string {
  const n = Math.max(10, Math.round(150 * v));
  const left: string[] = [];
  const right: string[] = [];
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    const c = centre(u * v);
    const h = Math.max(0.35, girth(u, scale)) / 2;
    left.push(`${(c.x + c.nx * h).toFixed(2)} ${(c.y + c.ny * h).toFixed(2)}`);
    right.push(`${(c.x - c.nx * h).toFixed(2)} ${(c.y - c.ny * h).toFixed(2)}`);
  }
  return `M${left.join("L")}L${right.reverse().join("L")}Z`;
}

/** Cerdas sueltas del final del trazo: líneas finas que se despegan del centro. */
function hairs(v: number): string[] {
  return [-0.27, 0.05, 0.3].map((off, k) => {
    const from = 0.5 + 0.08 * k;
    const n = Math.max(6, Math.round(70 * v));
    const pts: string[] = [];
    for (let i = 0; i <= n; i++) {
      const u = from + ((0.97 - from) * i) / n;
      const c = centre(u * v);
      const d = (girth(u, 1) / 2) * off * 2.4;
      pts.push(`${(c.x + c.nx * d).toFixed(2)} ${(c.y + c.ny * d).toFixed(2)}`);
    }
    return `M${pts.join("L")}`;
  });
}

const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Ensō: un círculo de pincel abierto que se completa con el progreso (0 a 1). */
export function Enso({ value, label, caption, tone, size = 132 }: { value: number; label: ReactNode; caption?: string; tone?: "warn"; size?: number }) {
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const fid = useId();
  const [shown, setShown] = useState(() => (reduced() ? v : 0));
  useEffect(() => {
    if (reduced()) { setShown(v); return; }
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 1100);
      setShown(v * (1 - Math.pow(1 - k, 3)));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [v]);
  const ink = tone === "warn" ? ({ "--brush": "var(--hi)" } as CSSProperties) : undefined;
  return (
    <svg className="enso" viewBox="0 0 100 100" width={size} height={size} role="img" aria-label={typeof label === "string" ? `${label}${caption ? `, ${caption}` : ""}` : caption}>
      <defs>
        <filter id={`${fid}-ink`} x="-10%" y="-10%" width="120%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.55" numOctaves="2" seed="7" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="1.7" />
        </filter>
      </defs>
      <path className="track" d={brushPath(1, 0.55)} />
      {shown > 0.01 && (
        <g filter={`url(#${fid}-ink)`} style={ink}>
          <path className="brush" d={brushPath(shown)} />
          {shown > 0.3 && hairs(shown).map((d, i) => <path key={i} className="hair" d={d} />)}
        </g>
      )}
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
