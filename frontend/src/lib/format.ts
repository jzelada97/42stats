const nf = new Intl.NumberFormat("es-ES");
const nf1 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });

export const fmt = (n: number | null | undefined): string => (n == null ? "–" : nf.format(n));
export const fmt1 = (n: number | null | undefined): string => (n == null ? "–" : nf1.format(n));
export const pct = (r: number | null | undefined): string => (r == null ? "–" : Math.round(r * 100) + " %");

export const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
export const DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];

const POOL_MONTHS: Record<string, string> = {
  january: "enero", february: "febrero", march: "marzo", april: "abril", may: "mayo", june: "junio", july: "julio",
  august: "agosto", september: "septiembre", october: "octubre", november: "noviembre", december: "diciembre",
};
/** La API da la piscina como «april 2026»; aquí se lee en español. Si no encaja, se deja tal cual. */
export const poolLabel = (p: string): string => p.replace(/^([A-Za-z]+)(?=\s)/, (m) => POOL_MONTHS[m.toLowerCase()] ?? m);

export const monthLabel = (m: string): string => `${MONTHS[+m.slice(5) - 1]} ${m.slice(2, 4)}`;
export const dayLabel = (d: string): string => `${+d.slice(8)} ${MONTHS[+d.slice(5, 7) - 1]}`;
export const weekLabel = dayLabel;
export const duration = (min: number | null | undefined): string =>
  min == null ? "–" : min >= 60 ? `${Math.floor(min / 60)} h ${min % 60} min` : `${min} min`;
export const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** El mes en curso está incompleto y haría caer la serie: se deja fuera. */
export const currentMonth = (): string => new Date().toISOString().slice(0, 7);
export const completeMonths = <T extends { month: string }>(rows: T[]): T[] => rows.filter((r) => r.month !== currentMonth());

const dateFmt = new Intl.DateTimeFormat("es-ES", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Madrid" });
const timeFmt = new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" });
export const agendaDate = (iso: string): string => dateFmt.format(new Date(iso));
export const agendaTime = (iso: string): string => timeFmt.format(new Date(iso));
/** Fecha y hora en la zona del navegador (el servidor guarda UTC). */
export const localTime = (iso: string | null | undefined): string => {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "?" : d.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });
};
