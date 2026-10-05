/** Fechas sin zona horaria: «aaaa-mm-dd» es lo que guarda y devuelve la API. */
export const MONTH_NAMES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
export const WEEKDAYS = ["L", "M", "X", "J", "V", "S", "D"];
const WEEKDAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];

export type Ymd = { y: number; m: number; d: number };      // m: 1 a 12

const pad = (n: number, w = 2) => String(n).padStart(w, "0");
export const toIso = ({ y, m, d }: Ymd): string => `${pad(y, 4)}-${pad(m)}-${pad(d)}`;

export function parseIso(s: string | null | undefined): Ymd | null {
  const k = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
  if (!k) return null;
  const v = { y: +k[1], m: +k[2], d: +k[3] };
  return v.m >= 1 && v.m <= 12 && v.d >= 1 && v.d <= daysInMonth(v.y, v.m) ? v : null;
}

export const daysInMonth = (y: number, m: number): number => new Date(Date.UTC(y, m, 0)).getUTCDate();
/** Lunes = 0 … domingo = 6. */
export const weekday = ({ y, m, d }: Ymd): number => (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;

export function addDays(v: Ymd, n: number): Ymd {
  const t = new Date(Date.UTC(v.y, v.m - 1, v.d + n));
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
}

export function addMonths(v: Ymd, n: number): Ymd {
  const idx = v.y * 12 + (v.m - 1) + n;
  const y = Math.floor(idx / 12);
  const m = (idx % 12) + 1;
  return { y, m, d: Math.min(v.d, daysInMonth(y, m)) };
}

export const sameDay = (a: Ymd | null, b: Ymd | null): boolean => !!a && !!b && a.y === b.y && a.m === b.m && a.d === b.d;

/** Las semanas de un mes, de lunes a domingo; null en los huecos de los extremos. */
export function monthGrid(y: number, m: number): (Ymd | null)[][] {
  const lead = weekday({ y, m, d: 1 });
  const cells: (Ymd | null)[] = [...Array(lead).fill(null), ...Array.from({ length: daysInMonth(y, m) }, (_, i) => ({ y, m, d: i + 1 }))];
  while (cells.length % 7) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, w) => cells.slice(w * 7, w * 7 + 7));
}

/** «dd/mm/aaaa», como se escribe aquí. */
export const showDate = (s: string | null | undefined): string => {
  const v = parseIso(s);
  return v ? `${pad(v.d)}/${pad(v.m)}/${pad(v.y, 4)}` : "";
};

/** Para lectores de pantalla: «lunes 5 de octubre de 2026». */
export const spokenDate = (v: Ymd): string => `${WEEKDAY_NAMES[weekday(v)]} ${v.d} de ${MONTH_NAMES[v.m - 1]} de ${v.y}`;

export function todayYmd(now = new Date()): Ymd {
  return { y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate() };
}
