import { Columns } from "./charts/Columns";
import { Empty } from "./ui";
import { fmt, fmt1 } from "../lib/format";

const SHORT = ["Más lento", "Medio-lento", "Medio-rápido", "Más rápido"];

export interface HabitsData {
  students: number;
  quartiles: { label: string; median_hours_30d: number }[];
  mine?: { quartile: number; hours_30d: number } | null;
}

/** Horas de uso por cuartil de ritmo. Solo agregados; es una correlación, no una causa. */
export function HabitsChart({ data }: { data: HabitsData }) {
  if (!data.quartiles.length) return <Empty>Aún no hay suficientes alumnos para comparar hábitos.</Empty>;
  const mine = data.mine ? data.mine.quartile : null;
  return (
    <Columns label="Horas de uso por cuartil de ritmo" labelEvery={1}
      data={data.quartiles.map((q, i) => ({ label: SHORT[i], full: q.label, value: q.median_hours_30d, hi: i === mine }))}
      tip={(x) => <>{x.full}: mediana <b>{fmt1(x.value)} h</b> en 30 días</>} />
  );
}

export function habitsSentence(h: HabitsData): string {
  const mine = h.mine
    ? `Estás en el grupo «${h.quartiles[h.mine.quartile].label.toLowerCase()}» de ${fmt(h.students)} alumnos y llevas ${fmt1(h.mine.hours_30d)} h en 30 días. `
    : "";
  return mine + "Es una correlación entre horas y ritmo: no demuestra que más horas den más nivel, pero sirve de referencia.";
}
