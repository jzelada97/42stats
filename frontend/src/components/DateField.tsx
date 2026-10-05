import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  MONTH_NAMES, WEEKDAYS, addDays, addMonths, monthGrid, parseIso, sameDay, showDate, spokenDate, todayYmd, toIso, weekday, type Ymd,
} from "../lib/dates";

/** Campo de fecha con un calendario propio (el del navegador no se puede teñir con la paleta). Valor: «aaaa-mm-dd» o "". */
export default function DateField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const uid = useId();
  const [open, setOpen] = useState(false);
  const picked = parseIso(value);
  const [focus, setFocus] = useState<Ymd>(() => picked ?? todayYmd());
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const grid = useRef<HTMLTableElement>(null);
  const wantFocus = useRef(false);                       // solo se mueve el foco al teclear o al abrir, no al pulsar «mes anterior»

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  useEffect(() => {
    if (open && wantFocus.current) {
      wantFocus.current = false;
      grid.current?.querySelector<HTMLButtonElement>('button[tabindex="0"]')?.focus();
    }
  }, [open, focus]);

  const show = () => { setFocus(picked ?? todayYmd()); wantFocus.current = true; setOpen(true); };
  const close = (back: boolean) => { setOpen(false); if (back) trigger.current?.focus(); };
  const choose = (v: Ymd) => { onChange(toIso(v)); close(true); };
  const move = (v: Ymd) => { wantFocus.current = true; setFocus(v); };

  function keys(e: KeyboardEvent) {
    const k = e.key;
    const jump: Record<string, Ymd> = {
      ArrowLeft: addDays(focus, -1), ArrowRight: addDays(focus, 1), ArrowUp: addDays(focus, -7), ArrowDown: addDays(focus, 7),
      Home: addDays(focus, -weekday(focus)), End: addDays(focus, 6 - weekday(focus)),
      PageUp: addMonths(focus, e.shiftKey ? -12 : -1), PageDown: addMonths(focus, e.shiftKey ? 12 : 1),
    };
    if (k === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
    else if (jump[k]) { e.preventDefault(); move(jump[k]); }
  }

  const weeks = monthGrid(focus.y, focus.m);
  const today = todayYmd();
  const title = `${MONTH_NAMES[focus.m - 1]} ${focus.y}`;
  return (
    <div className="datefield" ref={root} onKeyDown={open ? keys : undefined}
      onBlur={(e) => { if (open && e.relatedTarget && !root.current?.contains(e.relatedTarget as Node)) setOpen(false); }}>
      <span className="df-label" id={`${uid}-l`}>{label}</span>
      <div className="df-box">
        <button type="button" className="df-btn" ref={trigger} id={`${uid}-b`} aria-haspopup="dialog" aria-expanded={open}
          aria-labelledby={`${uid}-l ${uid}-b`} onClick={() => (open ? close(false) : show())}>
          <span className={value ? "" : "ph"}>{showDate(value) || "dd/mm/aaaa"}</span>
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
            <rect x="4" y="5.5" width="16" height="14.5" rx="3" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" />
          </svg>
        </button>
        {value && <button type="button" className="df-clear" aria-label={`Quitar ${label.toLowerCase()}`} onClick={() => onChange("")}>×</button>}
      </div>
      {open && (
        <div className="df-pop" role="dialog" aria-label={`Elegir ${label.toLowerCase()}`}>
          <div className="df-head">
            <button type="button" className="df-nav" aria-label="Mes anterior" onClick={() => setFocus(addMonths(focus, -1))}>‹</button>
            <strong aria-live="polite">{title}</strong>
            <button type="button" className="df-nav" aria-label="Mes siguiente" onClick={() => setFocus(addMonths(focus, 1))}>›</button>
          </div>
          <table className="df-grid" role="grid" aria-label={title} ref={grid}>
            <thead><tr>{WEEKDAYS.map((w, i) => <th key={i} scope="col" abbr={["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][i]}>{w}</th>)}</tr></thead>
            <tbody>
              {weeks.map((w, i) => (
                <tr key={i}>
                  {w.map((v, j) => (
                    <td key={j}>
                      {v && (
                        <button type="button" tabIndex={sameDay(v, focus) ? 0 : -1} aria-label={spokenDate(v)} aria-pressed={sameDay(v, picked)}
                          className={`df-day${sameDay(v, picked) ? " on" : ""}${sameDay(v, today) ? " today" : ""}`}
                          onClick={() => choose(v)}>{v.d}</button>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="df-foot">
            <button type="button" className="btn small ghost" onClick={() => choose(today)}>Hoy</button>
          </div>
        </div>
      )}
    </div>
  );
}
