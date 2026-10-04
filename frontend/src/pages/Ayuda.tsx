import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { TierBadge } from "../components/charts/Decor";
import { HELP_CHANGED, Shell, type NavLink } from "../components/Shell";
import { Card, Section } from "../components/ui";
import { get, post, useLoad } from "../lib/api";
import { fmt, localTime } from "../lib/format";
import { hostOf, profileUrl, safeUrl } from "../lib/safe";

/* ---------------------------------------------------------------- tipos (solo lo que se usa) */
interface Project { id: number; name: string; cursus_id: number | null; rank: number | null }
interface Rank { id: number | null; name: string; projects: number }
interface Validated { id: number; name: string; mark: number | null; rank: number | null; in_help: boolean }
interface Mentor { login: string; note: string; level: number | null; mark: number | null; validated_on: string | null; points: number; tier: string | null }
interface Responder { login: string; points: number; tier: string | null }
interface MyRequest { id: number; project: string; message: string; days: number; mentors: { login: string }[]; responders: Responder[] }
interface Incoming { id: number; login: string; project: string; message: string; offered: boolean; days_waiting: number }
interface Points { verified: number; pending: number; to_confirm: number; tier: string | null; next: { name: string; needs: number } | null }
interface Overview {
  is_admin: boolean;
  projects: Project[];
  ranks: Rank[];
  default_rank: number | null;
  validated: Validated[];
  offer: { active: boolean; note: string; project_ids: number[] } | null;
  requests: MyRequest[];
  incoming: Incoming[];
  points: Points;
  confirmations: { id: number; project: string; days: number }[];
}

const LINKS: NavLink[] = [
  { href: "/me", label: "Mi panel" },
  { href: "/campus", label: "Campus" },
  { href: "#recursos", label: "Recursos" },
  { href: "#mentoria", label: "Mentoría" },
  { href: "#peticiones", label: "Peticiones", badge: true },
  { href: "#pedir", label: "Pedir ayuda" },
];

const pts = (n: number) => `${n} ${n === 1 ? "punto" : "puntos"}`;
const verified = (n: number) => (n === 1 ? "verificado" : "verificados");

function ProfileLink({ login, className = "mono" }: { login: string; className?: string }) {
  const href = profileUrl(login);
  return href ? <a href={href} target="_blank" rel="noopener noreferrer nofollow" className={className}>{login}</a> : <span className={className}>{login}</span>;
}

function useOverview() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      setOv(await get<Overview>("/api/help/overview"));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return { ov, error, refresh };
}

const wantedProject = (() => {
  const v = Number(new URLSearchParams(location.search).get("project"));
  return Number.isInteger(v) && v > 0 ? v : null;
})();

/** Mantiene un valor de desplegable dentro de las opciones válidas. */
const keep = (current: string, valid: string[], fallback: string) => (valid.includes(current) ? current : fallback);

/* ---------------------------------------------------------------- recursos */
function Resources({ ov, here, rank, project, setProject, isAdmin, onAdminChange }: {
  ov: Overview; here: Project[]; rank: number | null; project: string; setProject: (v: string) => void; isAdmin: boolean; onAdminChange: () => void;
}) {
  const query = project ? `?project_id=${Number(project)}` : rank != null ? `?rank=${Number(rank)}` : "";
  const res = useLoad<{ resources: any[]; mine_pending: any[] }>("/api/help/resources" + query);
  return (
    <Section id="recursos" kicker="estudiar" title="Recursos de estudio" lead="Guías, documentación, vídeos y herramientas que explican el tema. Aprobados a mano.">
      <Card>
        <label className="inline">Proyecto
          <select value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">General (todo el círculo)</option>
            {here.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <ul className="list res">
          {res.data && !res.data.resources.length && <li className="empty">Aún no hay recursos aprobados para este proyecto. Propón el primero.</li>}
          {res.data?.resources.map((r) => {
            const href = safeUrl(r.url);
            return (
              <li key={r.id}>
                <span className="chip-kind">{r.kind}</span>
                <div>
                  {href ? <a className="t" href={href} target="_blank" rel="noopener noreferrer nofollow">{r.title}</a> : <span className="t">{r.title}</span>}
                  <div className="m">{r.project || "General"}</div>
                </div>
              </li>
            );
          })}
        </ul>
      </Card>
      {res.data && res.data.mine_pending.length > 0 && (
        <Card title="Tus envíos pendientes">
          <ul className="list plain">{res.data.mine_pending.map((r) => (
            <li key={r.id}><span className="t">{r.title}</span><span className="m">{r.status === "pending" ? "pendiente de revisión" : "rechazado"}</span></li>
          ))}</ul>
        </Card>
      )}
      <ProposeResource here={here} ov={ov} onSent={async () => { await res.reload(); if (isAdmin) onAdminChange(); }} />
    </Section>
  );
}

function ProposeResource({ here, onSent }: { here: Project[]; ov: Overview; onSent: () => Promise<void> }) {
  const [project, setProject] = useState("");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState("guía");
  const [ok, setOk] = useState(false);
  const [msg, setMsg] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setMsg("Enviando…");
    try {
      await post("/api/help/resources", { project_id: project ? Number(project) : null, title, url, kind, confirm_no_solution: ok });
      setMsg("Enviado: lo revisaremos antes de publicarlo.");
      setTitle(""); setUrl(""); setOk(false);
      await onSent();
    } catch (err) {
      setMsg((err as Error).message);
    }
  }
  return (
    <details className="card">
      <summary>Proponer un recurso</summary>
      <form className="stack" onSubmit={submit} noValidate>
        <label>Proyecto
          <select value={keep(project, here.map((p) => String(p.id)), "")} onChange={(e) => setProject(e.target.value)}>
            <option value="">General (todo el círculo)</option>
            {here.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label>Título<input type="text" maxLength={120} placeholder="Guía de punteros en C" value={title} onChange={(e) => setTitle(e.target.value)} required /></label>
        <label>Enlace (https)<input type="url" maxLength={300} placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} required /></label>
        <label>Tipo
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="guía">Guía o tutorial</option><option value="documentación">Documentación</option>
            <option value="vídeo">Vídeo</option><option value="herramienta">Herramienta</option><option value="otro">Otro</option>
          </select>
        </label>
        <label className="check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> <span>Confirmo que explica el tema y <b>no contiene la solución</b> del proyecto.</span></label>
        <div className="row"><button className="btn small" type="submit">Enviar a revisión</button><span className="sub" role="status">{msg}</span></div>
      </form>
    </details>
  );
}

/* ---------------------------------------------------------------- mentoría */
function MentorList({ here, project, setProject }: { here: Project[]; project: string; setProject: (v: string) => void }) {
  const { data } = useLoad<{ mentors: Mentor[] }>(project ? `/api/help/mentors?project_id=${Number(project)}` : null);
  return (
    <Card title="Mentores disponibles">
      <label className="inline">Proyecto
        <select value={project} onChange={(e) => setProject(e.target.value)}>
          {here.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <ul className="list mentors">
        {data && !data.mentors.length && <li className="empty">Nadie se ha ofrecido todavía en este proyecto.</li>}
        {data?.mentors.map((m) => {
          const meta = [m.level != null ? `nivel ${m.level}` : null, m.mark != null ? `nota ${m.mark}` : null, m.validated_on ? `validado el ${m.validated_on}` : null].filter(Boolean).join(" · ");
          return (
            <li key={m.login}>
              <div>
                <ProfileLink login={m.login} className="t mono" />
                {m.tier && <div className="tier" title={`${m.tier} · ${pts(m.points)} ${verified(m.points)}`}><TierBadge tier={m.tier} /><span>{m.tier}</span></div>}
              </div>
              <div><div className="m">{meta}</div>{m.note && <div className="note">{m.note}</div>}</div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function PointsPanel({ p }: { p: Points }) {
  if (!p.verified && !p.pending) return null;
  return (
    <div className="points">
      <div className="row"><TierBadge tier={p.tier} /><b>{p.tier || "Aún sin tramo"}</b><span className="m">{pts(p.verified)} {verified(p.verified)}</span></div>
      {p.pending > 0 && <div className="m">{p.pending} pendientes: cuentan cuando confirmes, y quien te agradeció valide el proyecto entre 48 horas y 120 días después de pedir ayuda.</div>}
      {p.next && <div className="m">Te faltan {p.next.needs} para {p.next.name}.</div>}
    </div>
  );
}

function OfferCard({ ov, rank, refresh }: { ov: Overview; rank: number | null; refresh: () => Promise<void> }) {
  const [chosen, setChosen] = useState<Set<number>>(new Set(ov.offer?.project_ids ?? []));
  const [note, setNote] = useState(ov.offer?.note ?? "");
  const [active, setActive] = useState(ov.offer ? ov.offer.active : true);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    setChosen(new Set(ov.offer?.project_ids ?? []));
    setNote(ov.offer?.note ?? "");
    setActive(ov.offer ? ov.offer.active : true);
  }, [ov.offer]);
  const offerable = ov.validated.filter((v) => v.in_help);
  const here = offerable.filter((v) => v.rank === rank);
  const hidden = offerable.length - here.length;
  const toggle = (id: number, on: boolean) => setChosen((s) => { const n = new Set(s); if (on) n.add(id); else n.delete(id); return n; });
  async function save(e: FormEvent) {
    e.preventDefault();
    setMsg("Guardando…");
    try {
      await post("/api/help/offer", { active, note, project_ids: [...chosen] });
      setMsg("Guardado.");
      await refresh();
    } catch (err) {
      setMsg((err as Error).message);
    }
  }
  return (
    <Card title="Ofrecer ayuda" sub="Elige entre los proyectos que ya tienes validados. Otros alumnos podrán ver tu login, tu nivel y tu nota en ese proyecto.">
      <PointsPanel p={ov.points} />
      <form className="stack" onSubmit={save} noValidate>
        <fieldset>
          <legend>Tus proyectos validados</legend>
          {!ov.validated.length && <p className="sub">Aún no tenemos proyectos validados tuyos. Cuando valides alguno podrás ofrecer ayuda.</p>}
          {ov.validated.length > 0 && !here.length && <p className="sub">{offerable.length ? "No tienes proyectos validados en este círculo. Cambia de círculo arriba para ver los demás." : "Ninguno de tus proyectos validados tiene sección de ayuda."}</p>}
          {here.map((v) => (
            <label className="check" key={v.id}>
              <input type="checkbox" checked={chosen.has(v.id)} onChange={(e) => toggle(v.id, e.target.checked)} /> <span>{v.name}{v.mark != null && <span className="m"> (nota {v.mark})</span>}</span>
            </label>
          ))}
          {hidden > 0 && here.length > 0 && <p className="sub">Y {hidden} validados en otros círculos (lo que hayas elegido allí se conserva).</p>}
        </fieldset>
        <label>Nota (opcional, 200 caracteres)<input type="text" maxLength={200} placeholder="Disponible por las tardes, explico punteros" value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> <span>Mostrarme como mentor</span></label>
        <div className="row"><button className="btn small" type="submit">Guardar</button><span className="sub" role="status">{msg}</span></div>
      </form>
    </Card>
  );
}

/* ---------------------------------------------------------------- peticiones de otros */
function IncomingItem({ r, refresh }: { r: Incoming; refresh: () => Promise<void> }) {
  const [msg, setMsg] = useState("");
  async function act(kind: "offer" | "withdraw") {
    try {
      await post(`/api/help/requests/${Number(r.id)}/${kind}`, {});
      await refresh();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  return (
    <li>
      <div>
        <div><span className="t">{r.project}</span> · <ProfileLink login={r.login} /></div>
        <p className="note">{r.message}</p>
        <div className="m">hace {r.days_waiting} días</div>
        {msg && <div className="m" role="status">{msg}</div>}
      </div>
      {r.offered
        ? <div className="close-box"><span className="m">Te ofreciste a ayudar.</span><button type="button" className="btn small ghost" onClick={() => act("withdraw")}>Retirar</button></div>
        : <button type="button" className="btn small" onClick={() => act("offer")}>Quiero ayudar</button>}
    </li>
  );
}

function Confirmations({ ov, refresh }: { ov: Overview; refresh: () => Promise<void> }) {
  const [ck, setCk] = useState<Record<number, boolean>>({});
  const [msg, setMsg] = useState("");
  async function answer(id: number, ok: boolean) {
    try {
      await post(`/api/help/thanks/${Number(id)}/confirm`, { ok, no_code: !!ck[id] });
      setMsg(ok ? "Confirmado. Tu punto cuenta cuando esa persona valide el proyecto." : "Anotado: ese agradecimiento no cuenta.");
      await refresh();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  if (!ov.confirmations.length) return null;
  return (
    <Card title="Agradecimientos por confirmar" sub="Alguien te agradeció su ayuda. Confirma solo si explicaste el tema sin dar código; si no fuiste tú, niégalo.">
      <ul className="list plain">
        {ov.confirmations.map((c) => (
          <li key={c.id}>
            <div><span className="t">{c.project}</span> <span className="m">hace {c.days} días</span></div>
            <label className="check small"><input type="checkbox" checked={!!ck[c.id]} onChange={(e) => setCk({ ...ck, [c.id]: e.target.checked })} /> <span>Expliqué el tema sin darle código</span></label>
            <div className="row">
              <button type="button" className="btn small" onClick={() => answer(c.id, true)}>Confirmar</button>
              <button type="button" className="btn small ghost" onClick={() => answer(c.id, false)}>No fui yo</button>
            </div>
          </li>
        ))}
      </ul>
      {msg && <p className="sub" role="status">{msg}</p>}
    </Card>
  );
}

function Incoming({ ov, refresh }: { ov: Overview; refresh: () => Promise<void> }) {
  const mentor = !!(ov.offer && ov.offer.active && ov.offer.project_ids.length);
  return (
    <Section id="peticiones" kicker="peticiones" title="Peticiones de otros alumnos" lead="Alumnos que piden ayuda en proyectos que tú ya validaste. Solo las ven quienes se han ofrecido como mentores en ese proyecto.">
      <Card>
        {!mentor && <p className="sub" role="status">Para ver las peticiones, ofrécete como mentor en un proyecto que ya hayas validado (arriba, en Mentoría).</p>}
        {mentor && !ov.incoming.length && <p className="sub" role="status">Ahora mismo nadie pide ayuda en tus proyectos.</p>}
        {mentor && ov.incoming.length > 0 && <p className="sub">Pulsa «Quiero ayudar» y quien pidió ayuda verá que te ofreces; el contacto es por tu perfil de 42.</p>}
        <ul className="list requests">{ov.incoming.map((r) => <IncomingItem key={r.id} r={r} refresh={refresh} />)}</ul>
      </Card>
      <Confirmations ov={ov} refresh={refresh} />
    </Section>
  );
}

/* ---------------------------------------------------------------- pedir ayuda */
function MyRequest({ r, refresh, say }: { r: MyRequest; refresh: () => Promise<void>; say: (m: string) => void }) {
  const [who, setWho] = useState("");
  const [noCode, setNoCode] = useState(false);
  async function close() {
    try {
      const res = await post(`/api/help/requests/${Number(r.id)}/close`, { helped_by: who || null, no_code: noCode });
      await refresh();
      say(res.thanked ? `Gracias enviado a ${res.thanked}. Su punto cuenta cuando confirme y tú valides el proyecto.` : "Petición cerrada.");
    } catch (e) {
      say((e as Error).message);
    }
  }
  return (
    <li>
      <div>
        <div><span className="t">{r.project}</span></div>
        <p className="note">{r.message}</p>
        <div className="m">hace {r.days} días</div>
        {r.responders.length > 0
          ? <div className="m">Se han ofrecido a ayudarte: {r.responders.map((m, i) => <span key={m.login}>{i > 0 && ", "}<ProfileLink login={m.login} />{m.tier ? ` (${m.tier})` : ""}</span>)}. Escríbeles por su perfil de 42.</div>
          : <div className="m">{r.mentors.length ? `Mentores disponibles: ${r.mentors.map((m) => m.login).join(", ")}. Aún nadie se ha ofrecido a esta petición.` : "Aún no hay mentores para este proyecto."}</div>}
      </div>
      <div className="close-box">
        {r.responders.length > 0 && (
          <>
            <select aria-label="¿Te ayudó alguien?" value={who} onChange={(e) => setWho(e.target.value)}>
              <option value="">Cerrar sin agradecer</option>
              {r.responders.map((m) => <option key={m.login} value={m.login}>Gracias a {m.login}</option>)}
            </select>
            {who && <label className="check small"><input type="checkbox" checked={noCode} onChange={(e) => setNoCode(e.target.checked)} /> <span>Me explicó, sin darme código</span></label>}
            <p className="m">El punto del mentor cuenta cuando él confirme y tú valides este proyecto.</p>
          </>
        )}
        <button type="button" className="btn small ghost" onClick={close}>Cerrar</button>
      </div>
    </li>
  );
}

function AskForHelp({ ov, here, project, setProject, refresh }: { ov: Overview; here: Project[]; project: string; setProject: (v: string) => void; refresh: () => Promise<void> }) {
  const [message, setMessage] = useState("");
  const [msg, setMsg] = useState("");
  const unvalidated = here.filter((p) => !ov.validated.some((v) => v.id === p.id));
  async function submit(e: FormEvent) {
    e.preventDefault();
    setMsg("Enviando…");
    try {
      const r = await post("/api/help/requests", { project_id: Number(project), message });
      setMessage("");
      setMsg(r.mentors.length ? `Hecho. Hay ${r.mentors.length} mentor(es) para este proyecto; si alguien se ofrece, lo verás aquí.` : "Hecho. Aún no hay mentores en este proyecto; tu petición queda abierta.");
      await refresh();
    } catch (err) {
      setMsg((err as Error).message);
    }
  }
  return (
    <Section id="pedir" kicker="pedir ayuda" title="¿Estás atascado?" lead="Describe qué has probado y qué no entiendes. Hasta 3 peticiones abiertas; caducan a los 30 días. Solo puedes pedir ayuda en proyectos que aún no has validado.">
      <div className="grid2">
        <Card>
          <form className="stack" onSubmit={submit} noValidate>
            <label>Proyecto
              <select value={project} onChange={(e) => setProject(e.target.value)}>
                {unvalidated.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label>Tu pregunta
              <textarea rows={4} maxLength={280} value={message} onChange={(e) => setMessage(e.target.value)}
                placeholder="Llevo 3 días con get_next_line: no entiendo por qué se pierde el resto del buffer entre llamadas." />
            </label>
            <div className="row"><span className="sub">{message.length} / 280</span><span className="sub">Los mentores de este proyecto verán tu login y tu mensaje.</span></div>
            <div className="row"><button className="btn small" type="submit">Pedir ayuda</button><span className="sub" role="status">{msg}</span></div>
          </form>
        </Card>
        <Card title="Tus peticiones">
          <ul className="list requests narrow">
            {!ov.requests.length && <li className="empty">No tienes peticiones abiertas.</li>}
            {ov.requests.map((r) => <MyRequest key={r.id} r={r} refresh={refresh} say={setMsg} />)}
          </ul>
        </Card>
      </div>
    </Section>
  );
}

/* ---------------------------------------------------------------- moderación */
function Pending({ tick }: { tick: number }) {
  const { data, reload } = useLoad<{ resources: any[] }>(`/api/admin/help/pending?t=${tick}`);
  const [msg, setMsg] = useState("");
  async function act(id: number, action: "approve" | "reject") {
    try {
      await post(`/api/admin/help/resources/${Number(id)}/${action}`, {});
      await reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  return (
    <Card title="Recursos pendientes de revisar">
      <ul className="list res">
        {data && !data.resources.length && <li className="empty">No hay nada pendiente.</li>}
        {data?.resources.map((r) => {
          const href = safeUrl(r.url);
          return (
            <li key={r.id}>
              <span className="chip-kind">{r.kind}</span>
              <div>
                {href ? <a className="t" href={href} target="_blank" rel="noopener noreferrer nofollow">{r.title}</a> : <span className="t">{r.title}</span>}
                <div className="m">{r.project} · enviado por {r.by}</div>
                <div className="m mono">destino: {hostOf(r.url)} · {r.url}</div>
              </div>
              <div className="row">
                <button type="button" className="btn small" onClick={() => act(r.id, "approve")}>Aprobar</button>
                <button type="button" className="btn small ghost" onClick={() => act(r.id, "reject")}>Rechazar</button>
              </div>
            </li>
          );
        })}
      </ul>
      {msg && <p className="sub" role="status">{msg}</p>}
    </Card>
  );
}

function Moderation({ tick }: { tick: number }) {
  const logins = useLoad<any>("/api/admin/logins");
  const abuse = useLoad<{ events: any[] }>("/api/admin/help/abuse");
  const points = useLoad<any>("/api/admin/help/points");
  const [msg, setMsg] = useState("");
  async function revoke(id: number) {
    if (!confirm("¿Anular este punto? No se podrá volver a dar para ese proyecto.")) return;
    try {
      await post(`/api/admin/help/thanks/${Number(id)}/revoke`, {});
      await points.reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  const l = logins.data;
  return (
    <Section id="moderacion" kicker="administración" title="Moderación">
      <Pending tick={tick} />
      <Card title="Accesos a la web" sub="Alumnos distintos que han entrado con 42. Solo se guarda login y fechas (no la IP) durante 90 días. Las horas son las de tu zona.">
        {l && (
          <>
            <div className="tiles">{([[l.day, "últimas 24 h"], [l.week, "7 días"], [l.month, "30 días"], [l.total, "en total"]] as [number, string][]).map(([n, label]) => (
              <div className="tile" key={label}><div className="v">{fmt(n)}</div><div className="l">{label}</div></div>
            ))}</div>
            <ul className="list plain">
              {!l.recent.length && <li className="empty">Todavía no ha entrado nadie desde que existe este registro.</li>}
              {l.recent.map((e: any) => <li key={e.login}><span className="t mono">{e.login}</span><span className="m">último acceso {localTime(e.last)} · {e.logins} {e.logins === 1 ? "vez" : "veces"}</span></li>)}
            </ul>
          </>
        )}
      </Card>
      <Card title="Puntos de mentoría" sub="Quién suma puntos, con cuántos alumnos distintos, y lo último que se ha agradecido. Un punto anulado no se puede volver a dar para ese proyecto.">
        {points.data && (
          <>
            <ul className="list plain">
              {!points.data.mentors.length && <li className="empty">Todavía no hay agradecimientos.</li>}
              {points.data.mentors.map((m: any) => (
                <li key={m.login}>
                  <span><span className="t mono">{m.login}</span> <span className="m">{m.verified} puntos · {m.pending} pendientes · {m.askers} alumnos distintos · {m.last7} en 7 días</span></span>
                  {m.flags.length > 0 && <span className="m" style={{ color: "var(--warn-ink)" }}>⚠ {m.flags.join(" · ")}</span>}
                </li>
              ))}
            </ul>
            <h3 className="mt">Últimos agradecimientos</h3>
            <ul className="list plain">
              {points.data.recent.map((r: any) => (
                <li key={r.id}>
                  <span><span className="mono">{r.asker ?? "(anónimo)"}</span> → <span className="t mono">{r.mentor}</span> <span className="m">· {r.project} · hace {r.days} días · {r.status}</span></span>
                  {!r.revoked && <button type="button" className="btn small ghost" onClick={() => revoke(r.id)}>Anular</button>}
                </li>
              ))}
            </ul>
          </>
        )}
        {msg && <p className="sub" role="status">{msg}</p>}
      </Card>
      <Card title="Límites alcanzados (30 días)" sub="Quién ha chocado con un límite de ritmo. Solo se registra el login y el tipo, nunca la IP. No bloquea a nadie por sí solo.">
        <ul className="list plain">
          {abuse.data && !abuse.data.events.length && <li className="empty">Nadie ha chocado con un límite.</li>}
          {abuse.data?.events.map((e) => <li key={e.login + e.kind}><span className="t mono">{e.login}</span><span className="m">{e.kind} · {e.hits} golpes · último {localTime(e.last)}</span></li>)}
        </ul>
      </Card>
    </Section>
  );
}

/* ---------------------------------------------------------------- página */
export default function Ayuda() {
  const { ov, error, refresh } = useOverview();
  const [rank, setRank] = useState<number | null | undefined>(undefined);
  const [resProject, setResProject] = useState("");
  const [mentorProject, setMentorProject] = useState("");
  const [reqProject, setReqProject] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!ov) return;
    if (rank === undefined || !ov.ranks.some((r) => r.id === rank)) {
      const linked = ov.projects.find((p) => p.id === wantedProject);
      const mine = ov.ranks.some((r) => r.id === ov.default_rank) ? ov.default_rank : ov.ranks[0] ? ov.ranks[0].id : null;
      setRank(linked ? linked.rank : mine);
    }
  }, [ov, rank]);

  const here = useMemo(() => (ov && rank !== undefined ? ov.projects.filter((p) => p.rank === rank) : []), [ov, rank]);
  useEffect(() => {
    if (!ov) return;
    const ids = here.map((p) => String(p.id));
    const wanted = wantedProject && ids.includes(String(wantedProject)) ? String(wantedProject) : "";
    const unvalidated = here.filter((p) => !ov.validated.some((v) => v.id === p.id)).map((p) => String(p.id));
    setResProject((c) => keep(c, ids, wanted));
    setMentorProject((c) => keep(c, ids, wanted || ids[0] || ""));
    setReqProject((c) => keep(c, unvalidated, (wanted && unvalidated.includes(wanted) ? wanted : unvalidated[0]) || ""));
  }, [ov, here]);

  useEffect(() => {
    if (ov && location.hash) document.querySelector(location.hash)?.scrollIntoView();
  }, [ov === null]);   // eslint-disable-line react-hooks/exhaustive-deps

  const refreshAll = useCallback(async () => { await refresh(); setTick((t) => t + 1); window.dispatchEvent(new Event(HELP_CHANGED)); }, [refresh]);

  let body: ReactNode;
  if (error && !ov) body = <main><Section kicker="comunidad" title="Ayuda entre alumnos"><p className="updated">No se pudo cargar la sección de ayuda ({error}).</p></Section></main>;
  else if (!ov || rank === undefined) body = <main><Section kicker="comunidad" title="Ayuda entre alumnos"><p className="updated">cargando…</p></Section></main>;
  else {
    body = (
      <main>
        <Section kicker="comunidad / ayuda entre alumnos" title="Aprender juntos, sin copiar" lead="Recursos para estudiar, alumnos que ya pasaron cada proyecto y un sitio para pedir ayuda.">
          <div className="notice-rule" role="note">
            <b>Una regla que no se negocia:</b> en 42, compartir o copiar la solución de un proyecto cuenta como <b>cheating</b>. Aquí ayudar es <b>explicar</b> conceptos, depurar con preguntas y orientar. <b>Nunca</b> pasar código ni enlaces a soluciones. Los recursos se revisan antes de publicarse.
          </div>
          <div className="cursus-bar">
            <label className="inline">Círculo
              <select value={rank == null ? "none" : String(rank)} onChange={(e) => setRank(e.target.value === "none" ? null : Number(e.target.value))}>
                {ov.ranks.map((r) => <option key={String(r.id)} value={r.id == null ? "none" : String(r.id)}>{r.name} ({r.projects})</option>)}
              </select>
            </label>
            <span className="sub">Elige el círculo y cada desplegable de proyectos mostrará solo los suyos.</span>
          </div>
        </Section>

        <Resources ov={ov} here={here} rank={rank} project={resProject} setProject={setResProject} isAdmin={ov.is_admin} onAdminChange={() => setTick((t) => t + 1)} />

        <Section id="mentoria" kicker="mentoría" title="Alumnos que ya lo pasaron" lead="Solo aparecen quienes, según nuestros datos, tienen el proyecto validado.">
          <div className="grid2">
            <MentorList here={here} project={mentorProject} setProject={setMentorProject} />
            <OfferCard ov={ov} rank={rank} refresh={refreshAll} />
          </div>
        </Section>

        <Incoming ov={ov} refresh={refreshAll} />
        <AskForHelp ov={ov} here={here} project={reqProject} setProject={setReqProject} refresh={refreshAll} />
        {ov.is_admin && <Moderation tick={tick} />}
      </main>
    );
  }
  return (
    <Shell sub="ayuda" links={LINKS}
      foot="Para contactar con un mentor usa su perfil de 42 o el canal habitual del campus: esta web no envía mensajes. Si ves algo que incumple las normas, avisa al staff. Los datos de mentoría y peticiones solo los ven alumnos con sesión.">
      {body}
    </Shell>
  );
}
