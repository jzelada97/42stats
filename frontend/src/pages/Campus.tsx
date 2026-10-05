import { useMemo, useState, type ReactNode } from "react";
import { Columns } from "../components/charts/Columns";
import { Heatmap, SeatMap } from "../components/charts/Heat";
import { LineChart } from "../components/charts/LineChart";
import { HabitsChart } from "../components/Habits";
import { Shell, useActiveSection, type NavLink } from "../components/Shell";
import { Card, DataTable, Disclosure, Empty, Failed, HBars, Meter, Section, Tiles, WAITING } from "../components/ui";
import { useLoad } from "../lib/api";
import { agendaDate, agendaTime, completeMonths, dayLabel, DAYS, duration, fmt, fmt1, monthLabel, pct, weekLabel } from "../lib/format";

const RES_NAMES: Record<string, string> = {
  users: "alumnos", cursus_users: "cursus", projects: "proyectos", events: "eventos", exams: "exámenes", project_users: "intentos de proyecto",
  quests: "milestones", quest_users: "milestones de alumnos", evaluations: "evaluaciones", locations: "sesiones de ordenador",
};

const LINKS: NavLink[] = [
  { href: "#resumen", label: "Resumen" },
  { href: "#ritmo", label: "Ritmo" },
  { href: "#asistencia", label: "Asistencia" },
  { href: "#proyectos", label: "Proyectos" },
  { href: "#evaluaciones", label: "Evaluaciones" },
  { href: "#eventos", label: "Eventos" },
];
const SECTION_IDS = ["resumen", "ritmo", "asistencia", "proyectos", "evaluaciones", "eventos"];

/** Una carga con su estado: cada tarjeta se pinta sola cuando llegan sus datos. */
function Data<T>({ path, children }: { path: string; children: (d: T) => ReactNode }) {
  const { data, error, loading } = useLoad<T>(path);
  if (error && !data) return <Failed message={error} />;
  if (loading || !data) return <Empty>Cargando…</Empty>;
  return <>{children(data)}</>;
}

function Overview() {
  const { data: o, error } = useLoad<any>("/api/overview");
  if (error && !o) return <Failed message={error} />;
  const loading: string[] = o?.loading ?? [];
  return (
    <>
      {loading.length > 0 && (
        <div className="notice" role="status">
          <b>Carga inicial en curso.</b> Aún se están descargando: {loading.map((r) => RES_NAMES[r] || r).join(", ")}. Hasta que termine, algunas cifras de esas secciones son parciales.
        </div>
      )}
      <p className="updated">
        {!o ? "cargando…" : o.last_sync
          ? "datos actualizados el " + new Date(o.last_sync).toLocaleString("es-ES", { dateStyle: "long", timeStyle: "short", timeZone: "Europe/Madrid" })
          : "sincronización en curso: los datos se irán completando"}
      </p>
      <Card raise className="hero">
        <div><div className="hero-num">{fmt(o?.cursus_current)}</div><div className="sub">alumnos activos en el 42cursus</div></div>
        {o && <Tiles items={[
          [o.avg_level == null ? "–" : fmt1(o.avg_level), "nivel medio"],
          [fmt(o.at_risk), `con fecha de blackhole (API) en menos de ${o.risk_days} días`],
          [fmt(o.cursus_graduated), "graduados (alumni)"],
          [fmt(o.cursus_closed), "cerraron el cursus sin graduarse"],
        ]} />}
      </Card>
    </>
  );
}

function ChartCard({ title, sub, children, table, note }: { title: string; sub?: ReactNode; children: ReactNode; table?: ReactNode; note?: ReactNode }) {
  return (
    <Card title={title} sub={sub}>
      {children}
      {note}
      {table && <Disclosure>{table}</Disclosure>}
    </Card>
  );
}

function Levels() {
  return (
    <Data<any[]> path="/api/levels">{(d) => !d.length ? <Empty>{WAITING}</Empty> : (
      <>
        <Columns label="Alumnos por nivel" labelEvery={1} data={d.map((x) => ({ label: String(x.level), value: x.count }))}
          tip={(x) => <>Nivel {x.label}: <b>{fmt(x.value)}</b> alumnos</>} />
        <Disclosure><DataTable head={["Nivel", "Alumnos"]} rows={d.map((x) => [x.level, fmt(x.count)])} /></Disclosure>
      </>
    )}</Data>
  );
}

function Signups() {
  return (
    <Data<any[]> path="/api/signups">{(raw) => {
      const d = completeMonths(raw);
      if (d.length < 2) return <Empty>{WAITING}</Empty>;
      return (
        <>
          <LineChart label="Altas por mes" data={d.map((x) => ({ label: x.month, value: x.count }))} xlabel={(x) => monthLabel(x.label)}
            tip={(x) => <>{monthLabel(x.label)}: <b>{fmt(x.value)}</b> altas</>} />
          <Disclosure><DataTable head={["Mes", "Altas"]} rows={d.slice().reverse().map((x) => [monthLabel(x.month), fmt(x.count)])} /></Disclosure>
        </>
      );
    }}</Data>
  );
}

function Blackholes() {
  return (
    <Data<any> path="/api/blackholes">{(b) => (
      <>
        <ChartCard title="Fechas de blackhole próximas (según la API)"
          sub={<>Alumnos con el cursus abierto cuya fecha de blackhole cae en cada semana (las próximas 26). <b>Orientativo:</b> es la fecha que devuelve la API pública y puede no coincidir con tu deadline real; en el currículo nuevo los milestones y los freezes no aparecen en ella.</>}
          table={b.upcoming ? <>
            <DataTable head={["Semana del", "Alumnos"]} rows={b.weeks.map((w: any) => [weekLabel(w.week), fmt(w.count)])} />
            {b.later ? <p className="sub">Y {fmt(b.later)} alumnos con el blackhole más adelante.</p> : null}
          </> : undefined}>
          {!b.upcoming ? <Empty>{WAITING}</Empty> : (
            <Columns label="Alumnos por semana de blackhole" data={b.weeks.map((w: any) => ({ label: weekLabel(w.week), value: w.count }))}
              tip={(x) => <>Semana del {x.label}: <b>{fmt(x.value)}</b> alumnos</>} />
          )}
        </ChartCard>
        <ChartCard title="Cursus cerrados por mes" sub="Alumnos cuyo cursus se cerró sin graduarse, por mes de cierre (últimos 24 meses). En 42 no hay baja voluntaria: quien deja de venir acaba blackholeado, así que casi todos son blackholes aunque la API no indique el motivo."
          note={b.stale ? <p className="sub">No se cuentan {fmt(b.stale)} alumnos con el cursus abierto y una fecha de blackhole ya pasada. Casi todos siguen activos: esa fecha no refleja su deadline real (milestones, freeze), que la API pública no expone.</p> : null}
          table={b.history_total ? <DataTable head={["Mes", "Cursus cerrados"]} rows={completeMonths<any>(b.history || []).slice().reverse().map((x) => [monthLabel(x.month), fmt(x.count)])} /> : undefined}>
          {!b.history_total ? <Empty>{WAITING}</Empty> : (
            <Columns label="Cursus cerrados por mes" data={completeMonths<any>(b.history || []).map((x) => ({ label: monthLabel(x.month), value: x.count }))}
              tip={(x) => <>{x.label}: <b>{fmt(x.value)}</b> cursus cerrados</>} />
          )}
        </ChartCard>
      </>
    )}</Data>
  );
}

function Cohorts() {
  return (
    <Data<any[]> path="/api/cohorts">{(d) => !d.length ? <Empty>{WAITING}</Empty> : (
      <DataTable head={["Año", "Entraron", "En el cursus", "Activos", "Graduados", "Cerraron sin graduarse", "% que cerró", "Nivel medio"]}
        rows={d.map((c) => [c.year, fmt(c.pool), fmt(c.in_cursus), fmt(c.current), fmt(c.graduated), fmt(c.closed),
          c.in_cursus ? <>{pct(c.closed / c.in_cursus)}<Meter value={c.closed / c.in_cursus} /></> : "–", c.avg_level == null ? "–" : fmt1(c.avg_level)])} />
    )}</Data>
  );
}

function Milestones() {
  return (
    <Data<any> path="/api/milestones">{(m) => {
      if (!m.ranks.length || !m.students) return <Empty>Aún no hay datos de milestones: la carga de quests sigue en curso.</Empty>;
      return (
        <>
          <div className="grid2">
            <ChartCard title="En qué rank están" sub="Alumnos con el cursus abierto, según el último Common Core Rank validado."
              table={<DataTable head={["Rank actual", "Alumnos"]} rows={m.by_rank.map((x: any) => [x.label, fmt(x.count)])} />}>
              <Columns label="Alumnos por rank" labelEvery={1} data={m.by_rank.map((x: any) => ({ label: x.label.replace("Rank ", "R"), full: x.label, value: x.count }))}
                tip={(x) => <>{x.full}: <b>{fmt(x.value)}</b> alumnos</>} />
            </ChartCard>
            <ChartCard title="Cuánto llevan sin validar un milestone" sub="Días desde el último rank validado (o desde que empezaron, si aún no tienen ninguno)."
              table={<DataTable head={["Sin validar desde hace", "Alumnos"]} rows={m.stalled.map((x: any) => [x.label, fmt(x.count)])} />}>
              <Columns label="Alumnos por tiempo sin validar" labelEvery={1} data={m.stalled.map((x: any) => ({ label: x.label.replace(" días", "d"), full: x.label, value: x.count }))}
                tip={(x) => <>{x.full}: <b>{fmt(x.value)}</b> alumnos</>} />
            </ChartCard>
          </div>
          <Card title="Cuánto tardan entre milestones" sub="Mediana de días entre un rank y el siguiente, con todos los alumnos que validaron ambos.">
            {m.steps.length
              ? <HBars rows={m.steps.map((x: any) => ({ name: x.label, value: x.median_days, text: `${fmt1(x.median_days)} días · ${fmt(x.n)} alumnos` }))} />
              : <Empty>{WAITING}</Empty>}
          </Card>
        </>
      );
    }}</Data>
  );
}

function Attendance() {
  return (
    <Data<any> path="/api/attendance">{(a) => {
      if (!a.sessions) return <Empty>Aún no hay sesiones: la carga del histórico sigue en curso.</Empty>;
      return (
        <>
          <Card raise><Tiles items={[
            [fmt(a.total_hours), "horas de uso", "h"],
            [fmt(a.unique_users), "alumnos distintos"],
            [duration(a.avg_session_min), "duración media de sesión"],
            [a.peak ? `${DAYS[a.peak.weekday]} ${String(a.peak.hour).padStart(2, "0")}:00` : "–", a.peak ? `hora punta · ${fmt1(a.peak.value)} puestos de media` : "hora punta"],
          ]} /></Card>
          <Card title="Puestos ocupados por día y hora" sub="Media de puestos ocupados a la vez, por día de la semana y hora, en los últimos 90 días.">
            <Heatmap cells={a.heatmap} />
            <div className="legend"><span>menos</span><i /><span>más</span></div>
          </Card>
          <div className="grid2">
            <ChartCard title="Horas de uso por día" sub="Suma de todas las sesiones de cada día, últimos 90 días."
              table={<DataTable head={["Día", "Horas", "Alumnos"]} rows={a.daily.slice().reverse().map((d: any) => [dayLabel(d.date), fmt1(d.hours), fmt(d.users)])} />}>
              <LineChart label="Horas de uso por día" data={a.daily.map((d: any) => ({ label: d.date, value: d.hours, users: d.users }))} xlabel={(x) => dayLabel(x.label)}
                tip={(x) => <>{dayLabel(x.label)}: <b>{fmt1(x.value)} h</b> · {fmt(x.users)} alumnos</>} />
            </ChartCard>
            <ChartCard title="Duración de las sesiones" sub="Número de sesiones según lo que duran, últimos 90 días."
              table={<DataTable head={["Duración", "Sesiones"]} rows={a.durations.map((d: any) => [d.label, fmt(d.count)])} />}>
              <Columns label="Sesiones por duración" labelEvery={1} data={a.durations.map((d: any) => ({ label: d.label, value: d.count }))}
                tip={(x) => <>{x.label}: <b>{fmt(x.value)}</b> sesiones</>} />
            </ChartCard>
          </div>
          <Card title="Mapa de puestos" sub="Sesiones por puesto en los últimos 90 días: fila en vertical, puesto en horizontal, un panel por cluster. Más intenso, más usado.">
            {a.seats.length ? <SeatMap seats={a.seats} /> : <Empty>Sin datos de puestos.</Empty>}
            <div className="legend"><span>menos</span><i /><span>más</span></div>
          </Card>
        </>
      );
    }}</Data>
  );
}

const PCOLS: [key: string, label: string, numeric: boolean][] = [
  ["name", "Proyecto", false], ["attempts", "Intentos", true], ["in_progress", "En curso", true], ["finished", "Terminados", true],
  ["validation_rate", "Validación", true], ["avg_mark", "Nota media", true], ["median_days", "Mediana (días)", true],
];

function CursusCard({ g, q, sortKey, dir, onSort, open0 }: { g: any; q: string; sortKey: string; dir: 1 | -1; onSort: (k: string) => void; open0: boolean }) {
  const [open, setOpen] = useState(open0);
  const rows = useMemo(() => (g.rows as any[]).filter((r) => !q || r.name.toLowerCase().includes(q)).sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
  }), [g, q, sortKey, dir]);
  if (q && !rows.length) return null;
  return (
    <details className="card cursus" open={q ? true : open} onToggle={(e) => { if (!q) setOpen(e.currentTarget.open); }}>
      <summary><h3>{(g.names as string[]).join(" · ")}</h3><span className="sub">{fmt(g.projects_count)} proyectos · {fmt(g.attempts)} intentos</span></summary>
      <div className="wrap">
        <table>
          <thead><tr>{PCOLS.map(([k, l, n]) => (
            <th key={k} className={`sort${n ? " n" : ""}`} tabIndex={0} aria-sort={sortKey === k ? (dir > 0 ? "ascending" : "descending") : undefined}
              onClick={() => onSort(k)} onKeyDown={(e) => { if (e.key === "Enter") onSort(k); }}>{l}</th>
          ))}</tr></thead>
          <tbody>{rows.map((p) => (
            <tr key={p.id ?? p.name}>
              <td>{p.name}</td><td className="n">{fmt(p.attempts)}</td><td className="n">{fmt(p.in_progress)}</td><td className="n">{fmt(p.finished)}</td>
              <td className="n">{pct(p.validation_rate)}<Meter value={p.validation_rate} /></td>
              <td className="n">{p.avg_mark == null ? "–" : fmt1(p.avg_mark)}</td><td className="n">{p.median_days == null ? "–" : fmt1(p.median_days)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </details>
  );
}

function Projects() {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "attempts", dir: -1 });
  const onSort = (k: string) => setSort((s) => ({ key: k, dir: s.key === k ? (s.dir === 1 ? -1 : 1) : k === "name" ? 1 : -1 }));
  return (
    <>
      <div className="tools">
        <div>
          <h3>Proyectos más intentados, por cursus</h3>
          <p className="sub">Un cuadro por cursus, según el cursus en el que el alumno de Madrid hizo el intento. Validación sobre los terminados; «mediana» = días entre empezar y recibir la nota. No cuentan los intentos con cheating (nota −42) ni, en la media, las notas fuera de 0-125 (datos erróneos de la API).</p>
        </div>
        <input type="search" placeholder="Filtrar por proyecto…" aria-label="Filtrar proyectos" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Data<any[]> path="/api/projects">{(d) => !d.length ? <Empty>Aún no hay proyectos con intentos suficientes: la carga sigue en curso.</Empty> : (
        <div className="cursus-list">
          {d.map((g, i) => <CursusCard key={(g.names as string[]).join("|")} g={g} q={q.trim().toLowerCase()} sortKey={sort.key} dir={sort.dir} onSort={onSort} open0={i < 3} />)}
        </div>
      )}</Data>
      <ProjectsMonthly />
    </>
  );
}

function ProjectsMonthly() {
  return (
    <Data<any[]> path="/api/projects/monthly">{(raw) => {
      const d = completeMonths(raw);
      return (
        <Card title="Proyectos terminados por mes" sub="Con nota registrada, validados o no, sin contar el mes en curso.">
          {d.length < 2 ? <Empty>{WAITING}</Empty> : (
            <>
              <Columns label="Proyectos terminados por mes" data={d.map((x) => ({ label: monthLabel(x.month), value: x.validated + x.failed, v: x.validated, f: x.failed }))}
                tip={(x) => <>{x.label}: <b>{fmt(x.value)}</b> terminados<br />{fmt(x.v)} validados · {fmt(x.f)} no validados</>} />
              <Disclosure><DataTable head={["Mes", "Validados", "No validados"]} rows={d.slice().reverse().map((x) => [monthLabel(x.month), fmt(x.validated), fmt(x.failed)])} /></Disclosure>
            </>
          )}
        </Card>
      );
    }}</Data>
  );
}

function Evaluations() {
  return (
    <Data<any> path="/api/evaluations">{(e) => {
      if (!e.total) return <Empty>Aún no hay evaluaciones: la carga sigue en curso.</Empty>;
      const monthly = completeMonths<any>(e.monthly);
      return (
        <>
          <Card raise><Tiles items={[
            [fmt(e.total), "evaluaciones completadas"], [fmt1(e.avg_mark), "nota media"], [pct(e.positive_share), "con resultado positivo"],
            [fmt(e.active_correctors_90d), "alumnos evaluando (90 días)"], [fmt(e.scheduled), "programadas ahora"],
          ]} /></Card>
          <div className="grid2">
            <ChartCard title="Evaluaciones por mes" sub="Evaluaciones completadas, sin contar el mes en curso."
              table={monthly.length > 1 ? <DataTable head={["Mes", "Evaluaciones", "Nota media"]} rows={monthly.slice().reverse().map((x) => [monthLabel(x.month), fmt(x.count), fmt1(x.avg_mark)])} /> : undefined}>
              {monthly.length > 1
                ? <LineChart label="Evaluaciones por mes" data={monthly.map((x) => ({ label: x.month, value: x.count, avg: x.avg_mark }))} xlabel={(x) => monthLabel(x.label)}
                    tip={(x) => <>{monthLabel(x.label)}: <b>{fmt(x.value)}</b> evaluaciones · nota media {fmt1(x.avg)}</>} />
                : <Empty>{WAITING}</Empty>}
            </ChartCard>
            <Card title="Resultado de las evaluaciones" sub="Según el flag que marca quien evalúa.">
              <HBars rows={e.flags.map((f: any) => ({ name: f.name, value: f.count, text: `${fmt(f.count)} · ${pct(f.count / e.total)}` }))} />
            </Card>
          </div>
          <Card title="Distribución de notas" sub="Nota final de las evaluaciones completadas.">
            <Columns label="Evaluaciones por nota" labelEvery={1} data={e.marks.map((m: any) => ({ label: m.label, value: m.count }))}
              tip={(x) => <>Nota {x.label}: <b>{fmt(x.value)}</b> evaluaciones</>} />
          </Card>
        </>
      );
    }}</Data>
  );
}

function Agenda({ items, kind }: { items: any[]; kind: boolean }) {
  if (!items.length) return <ul className="list"><li className="empty"><span>No hay nada programado.</span></li></ul>;
  return (
    <ul className="list">
      {items.map((i, k) => (
        <li key={k}>
          <time dateTime={i.begin_at}>{agendaDate(i.begin_at)}<br />{agendaTime(i.begin_at)}</time>
          <div><div className="t">{i.name}</div><div className="m">{[kind ? i.kind : null, i.location].filter(Boolean).join(" · ") || " "}</div></div>
          <div>{i.subscribers == null ? "" : <>{fmt(i.subscribers)}{i.max_people ? ` / ${fmt(i.max_people)}` : ""} <span className="m">inscritos</span></>}</div>
        </li>
      ))}
    </ul>
  );
}

function Events() {
  return (
    <Data<any> path="/api/events">{(x) => (
      <>
        <div className="grid2">
          <Card title="Próximos eventos"><Agenda items={x.upcoming_events} kind /></Card>
          <Card title="Próximos exámenes"><Agenda items={x.upcoming_exams} kind={false} /></Card>
        </div>
        <div className="grid2">
          <ChartCard title="Eventos por mes"
            table={x.events_monthly.length > 1 ? <DataTable head={["Mes", "Eventos"]} rows={x.events_monthly.slice().reverse().map((m: any) => [monthLabel(m.month), fmt(m.count)])} /> : undefined}>
            {x.events_monthly.length > 1
              ? <Columns label="Eventos por mes" data={x.events_monthly.map((m: any) => ({ label: monthLabel(m.month), value: m.count }))} tip={(d) => <>{d.label}: <b>{fmt(d.value)}</b> eventos</>} />
              : <Empty>{WAITING}</Empty>}
          </ChartCard>
          <Card title="Tipos de evento" sub="Número de eventos y media de inscritos.">
            {x.kinds.length
              ? <HBars rows={x.kinds.map((k: any) => ({ name: k.kind, value: k.count, text: `${fmt(k.count)} · ${fmt1(k.avg_subscribers)} insc.` }))} />
              : <Empty>{WAITING}</Empty>}
          </Card>
        </div>
      </>
    )}</Data>
  );
}

export default function Campus() {
  const active = useActiveSection(SECTION_IDS);
  return (
    <Shell sub="campus Madrid" links={LINKS} current={active} foot="Solo datos agregados: no se muestra ninguna persona. Fuente: API pública de 42, sincronizada cada noche.">
      <main>
        <Section id="resumen" kicker="campus / resumen" title="Cómo está el campus hoy">
          <Overview />
          <div className="grid2">
            <Card title="Distribución de niveles" sub="Alumnos con el cursus abierto, por nivel (parte entera)."><Levels /></Card>
            <Card title="Altas por mes" sub="Cuentas de alumno creadas cada mes (entradas a la piscina), sin contar el mes en curso."><Signups /></Card>
          </div>
          <Blackholes />
          <Card title="Promociones" sub="Agrupado por año de piscina (cuándo entraron). «Activos»: cursus abierto sin graduarse. «Graduados»: alumni. «Cerraron sin graduarse»: cursus cerrado; en 42 no existe la baja voluntaria (quien se va deja de venir y acaba blackholeado), así que son casi todos blackholes, aunque la fecha de blackhole de la API es orientativa y no refleja los plazos por milestone ni los freezes. Las promociones recientes aún están dentro de plazo.">
            <Cohorts />
          </Card>
        </Section>

        <Section id="ritmo" kicker="42cursus / milestones" title="A qué ritmo avanzan"
          lead="Los milestones son los Common Core Rank 00 a 05. El deadline de cada uno y los freezes no están en la API pública de 42, así que esto mide el ritmo, no los días que quedan.">
          <Milestones />
          <Card title="Qué hacen los que avanzan más rápido" sub="Alumnos con el cursus abierto agrupados en cuatro cuartiles de ritmo (nivel por mes) y su mediana de horas en 30 días. Es una correlación, no una causa.">
            <Data<any> path="/api/habits">{(h) => <HabitsChart data={h} />}</Data>
          </Card>
        </Section>

        <Section id="asistencia" kicker="cluster / asistencia · últimos 90 días" title="Cuándo y dónde se trabaja"
          lead="Sesiones de ordenador en los clusters, en hora de Madrid. Mide ocupación, no presencia en el edificio.">
          <Attendance />
        </Section>

        <Section id="proyectos" kicker="42cursus / proyectos" title="Qué se entrega y qué se atasca"><Projects /></Section>

        <Section id="evaluaciones" kicker="peer evaluation / evaluaciones" title="Cómo se evalúan entre sí"
          lead="Solo recuentos y notas. No se guardan ni se muestran comentarios ni quién evaluó a quién.">
          <Evaluations />
        </Section>

        <Section id="eventos" kicker="agenda / eventos y exámenes" title="Qué viene"><Events /></Section>
      </main>
    </Shell>
  );
}
