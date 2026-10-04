import { useEffect, useState, type FormEvent } from "react";
import { Columns } from "../components/charts/Columns";
import { Enso } from "../components/charts/Decor";
import { HabitsChart, habitsSentence } from "../components/Habits";
import { Shell, type NavLink } from "../components/Shell";
import { Card, DataTable, Disclosure, Empty, Section, Tiles } from "../components/ui";
import { post, useLoad } from "../lib/api";
import { fmt, fmt1, MONTHS, pct } from "../lib/format";

const LINKS: NavLink[] = [];
const STATE_ICON: Record<string, string> = { good: "✓", ok: "•", warn: "!" };
const STATE_TEXT: Record<string, string> = { good: "Bien", ok: "Normal", warn: "A vigilar" };
const STATUS_ICON: Record<string, string> = { great: "✓", normal: "•", attention: "!", frozen: "❄", none: "–" };

/** Línea de milestones como un tallo de bambú: un nudo por cada rank validado. */
function Bamboo({ d }: { d: any }) {
  const done = d.milestones as any[];
  const next = d.next_milestone;
  if (!done.length && !next) return <p className="sub">Aún no hay milestones registrados.</p>;
  return (
    <ol className="bamboo">
      {done.map((m) => (
        <li key={m.label}>
          <b>{m.label}</b>
          <span className="mono">{m.date}</span>
          <span className="sub">{m.days_from_previous == null ? "" : `${fmt(m.days_from_previous)} días desde el anterior`}</span>
        </li>
      ))}
      {next && (
        <li className="next">
          <b>{next.label}</b>
          <span className="mono">pendiente</span>
          <span className="sub">
            {next.days_since_last == null ? "" : `llevas ${fmt(next.days_since_last)} días`}
            {next.typical_days == null ? "" : ` · lo habitual: ${fmt(Math.round(next.typical_days))}`}
          </span>
        </li>
      )}
    </ol>
  );
}

function SelfForm({ initial, onSaved }: { initial: { deadline?: string | null; freeze_until?: string | null }; onSaved: () => Promise<void> }) {
  const [deadline, setDeadline] = useState(initial.deadline || "");
  const [freeze, setFreeze] = useState(initial.freeze_until || "");
  const [msg, setMsg] = useState("");
  useEffect(() => { setDeadline(initial.deadline || ""); setFreeze(initial.freeze_until || ""); }, [initial.deadline, initial.freeze_until]);
  async function save(dl: string, fr: string) {
    setMsg("Guardando…");
    try {
      await post("/api/me/settings", { deadline: dl || null, freeze_until: fr || null });
      await onSaved();
      setMsg(dl || fr ? "Guardado." : "Borrado.");
    } catch (e) {
      setMsg(`No se pudo guardar: ${(e as Error).message}`);
    }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void save(deadline, freeze); };
  return (
    <Card title="Tu deadline y tu freeze" sub="42 no los publica en su API, así que indícalos tú y los usamos en el análisis. Solo los ves tú y puedes borrarlos cuando quieras.">
      <form className="self-form" onSubmit={submit} noValidate>
        <label>Deadline de tu milestone<input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} /></label>
        <label>Freeze hasta<input type="date" value={freeze} onChange={(e) => setFreeze(e.target.value)} /></label>
        <div className="self-actions">
          <button className="btn small" type="submit">Guardar</button>
          <button className="btn small ghost" type="button" onClick={() => { setDeadline(""); setFreeze(""); void save("", ""); }}>Borrar</button>
          <span className="sub" role="status">{msg}</span>
        </div>
      </form>
    </Card>
  );
}

function EraseCard() {
  const [msg, setMsg] = useState("");
  async function erase() {
    if (!confirm("Se borrará todo lo que guardamos de ti en esta web y se cerrará tu sesión. ¿Seguro?")) return;
    try {
      await post("/api/me/delete", {});
      location.replace("/");
    } catch (e) {
      setMsg(`No se pudo borrar: ${(e as Error).message}`);
    }
  }
  return (
    <Card title="Tus datos en esta web"
      sub="Aquí guardamos solo lo que tú escribes: deadline y freeze manuales, tu oferta de mentoría, tus peticiones y los recursos que envías. Si chocas con un límite de ritmo, se anota tu login y el tipo de límite durante 30 días. Para saber cuántos alumnos usan la web se guardan tu primer y último acceso y cuántas veces entras (sin IP) durante 90 días. Los agradecimientos de mentoría que das o recibes también se guardan, y se borran con el resto. Si activas los avisos por correo, guardamos tu dirección hasta que los desactives o borres tus datos. Las peticiones se borran al cerrarlas o a los 30 días. Si quieres, bórralo todo ahora y se cierra tu sesión.">
      <div className="row"><button className="btn small ghost" type="button" onClick={erase}>Borrar mis datos</button><span className="sub" role="status">{msg}</span></div>
    </Card>
  );
}

export default function Me() {
  const { data: d, error, reload } = useLoad<any>("/api/me");
  if (error && !d) {
    return (
      <Shell sub="mi panel" links={LINKS}>
        <main><Section kicker="mi panel" title="Cómo vas"><p className="updated">No se pudo cargar tu panel ({error}). Inténtalo de nuevo en unos minutos.</p></Section></main>
      </Shell>
    );
  }
  if (!d) {
    return <Shell sub="mi panel" links={LINKS}><main><Section kicker="mi panel" title="Cómo vas"><p className="updated">cargando…</p></Section></main></Shell>;
  }
  const lc = d.level_context;
  const weekly = d.activity.weekly.map((x: any) => ({ label: `${+x.week.slice(8)} ${MONTHS[+x.week.slice(5, 7) - 1]}`, value: x.hours }));
  const p = d.projects;
  const e = d.evaluations;
  const next = d.next_milestone;
  return (
    <Shell sub="mi panel" links={LINKS}
      foot={<>Solo tú ves esta página: depende de tu sesión de 42 y no se comparte con nadie. Las comparaciones usan datos agregados de tu cursus.
        La fecha de blackhole que devuelve la API pública es orientativa y puede no coincidir con tu deadline real.
        {d.blackhole_api ? ` Fecha de blackhole según la API: ${d.blackhole_api}.` : ""}</>}>
      <main>
        <Section kicker={`mi panel · ${d.login}`} title="Cómo vas">
          {d.pool && <p className="updated">piscina {d.pool}</p>}
          <Card raise className="status">
            <div data-state={d.status.key} className="status-grid">
              <div className="status-main">
                <span className="chip">{STATUS_ICON[d.status.key] || ""} {d.status.label}</span>
                <p className="lead">{d.status.summary}</p>
              </div>
              {next && next.typical_days ? (
                <Enso value={(next.days_since_last ?? 0) / next.typical_days} tone={(next.days_since_last ?? 0) > next.typical_days ? "warn" : undefined}
                  label={fmt(next.days_since_last ?? 0)} caption={`de ~${fmt(Math.round(next.typical_days))} días`} />
              ) : null}
            </div>
            <Tiles items={[
              [d.level == null ? "–" : fmt1(d.level), "tu nivel"],
              [d.days_in_cursus == null ? "–" : fmt(d.days_in_cursus), "días en el cursus"],
              [d.milestones.length ? d.milestones[d.milestones.length - 1].label : "–", "último rank validado"],
              [fmt1(d.activity.hours_30d), "horas en 30 días"],
            ]} />
          </Card>

          <div className="signals">
            {d.signals.map((x: any) => (
              <article className="card sig" data-state={x.state} key={x.key ?? x.label}>
                <div className="sig-head"><span className="state">{STATE_ICON[x.state]} {STATE_TEXT[x.state]}</span><h3>{x.label}</h3></div>
                <div className="sig-val">{x.value}</div>
                <p className="sub">{x.detail}</p>
              </article>
            ))}
          </div>

          <SelfForm initial={d.self_reported || {}} onSaved={reload} />

          {d.tips.length > 0 && (
            <Card title="Qué puedes hacer esta semana"><ul className="tips">{d.tips.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul></Card>
          )}

          <Card className="cta" raise>
            <div><h3>Ayuda entre alumnos</h3>
              <p className="sub">Recursos de estudio revisados, mentores que ya validaron cada proyecto y un sitio para pedir ayuda. Y si ya pasaste proyectos, puedes ofrecerte como mentor.</p></div>
            <a className="btn small" href="/ayuda">Ir a Ayuda</a>
          </Card>
        </Section>

        <Section kicker="42cursus / milestones" title="Tus milestones">
          <div className="grid2">
            <Card title="Common Core Rank" sub="Fecha de cada rank y días desde el anterior."><Bamboo d={d} /></Card>
            <Card title="Tu nivel frente a tu cursus"
              sub={lc.percentile != null && lc.my_bucket != null ? `Alumnos con el cursus abierto por nivel. Tu ritmo (nivel por mes) supera al ${Math.round(lc.percentile * 100)} % de ellos.` : "Alumnos con el cursus abierto por nivel; tu columna aparece marcada."}>
              {lc.my_bucket != null && lc.hist.length
                ? <Columns label="Alumnos por nivel; tu nivel marcado" labelEvery={1} data={lc.hist.map((x: any) => ({ label: String(x.level), value: x.count, hi: x.level === lc.my_bucket }))}
                    tip={(x) => <>Nivel {x.label}: <b>{fmt(x.value)}</b> alumnos</>} />
                : <Empty>No hay nivel que comparar: no tienes el 42cursus abierto.</Empty>}
            </Card>
          </div>
        </Section>

        <Section kicker="campus / actividad" title="Tu actividad">
          <div className="grid2">
            <Card title="Horas por semana" sub="Sesiones de ordenador en el campus, últimas 12 semanas.">
              <Columns label="Horas por semana" data={weekly} tip={(x) => <>Semana del {x.label}: <b>{fmt1(x.value)} h</b></>} />
              <Disclosure><DataTable head={["Semana del", "Horas"]} rows={weekly.slice().reverse().map((x: any) => [x.label, fmt1(x.value)])} /></Disclosure>
            </Card>
            <Card title="Proyectos y evaluaciones">
              <Tiles items={[[fmt(p.validated_90d), "proyectos validados (90 días)"], [fmt(e.done_90d), "evaluaciones hechas (90 días)"],
                [e.correction_points == null ? "–" : fmt(e.correction_points), "puntos de corrección"]]} />
              <h3 className="mt">En curso ahora</h3>
              {p.in_progress.length ? (
                <ul className="list plain">
                  {p.in_progress.map((x: any) => (
                    <li key={x.id}>
                      <div><span className="t">{x.name}</span> <span className="m">{x.days == null ? "" : `desde hace ${fmt(x.days)} días`}</span></div>
                      {x.context && <div className="m">Lo habitual: validarlo en {x.context.median_days == null ? "–" : fmt1(x.context.median_days)} días · lo valida el {pct(x.context.validation_rate)} · nota media {fmt1(x.context.avg_mark)}</div>}
                      {x.help && <div className="m">
                        <a href={`/ayuda?project=${Number(x.id)}#recursos`}>{fmt(x.resources)} recursos</a> · <a href={`/ayuda?project=${Number(x.id)}#mentoria`}>{fmt(x.mentors)} mentores</a> · <a href={`/ayuda?project=${Number(x.id)}#pedir`}>Pedir ayuda</a>
                      </div>}
                    </li>
                  ))}
                </ul>
              ) : <p className="sub">No tienes proyectos en curso.</p>}
            </Card>
          </div>
          {d.habits && (
            <Card title="Qué hacen los que avanzan más rápido" sub={habitsSentence(d.habits)}><HabitsChart data={d.habits} /></Card>
          )}
        </Section>

        <EraseCard />
      </main>
    </Shell>
  );
}
