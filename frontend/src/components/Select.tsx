import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

export interface Option { value: string; label: string }

/**
 * Desplegable propio (el del navegador no admite la paleta). Patrón «select-only combobox»: el foco se queda en el botón y
 * la opción activa se anuncia con aria-activedescendant. Flechas, Inicio/Fin, escribir la inicial, Intro/Espacio y Esc.
 */
export default function Select({ label, ariaLabel, value, options, onChange, inline = false }: {
  label?: string; ariaLabel?: string; value: string; options: Option[]; onChange: (v: string) => void; inline?: boolean;
}) {
  const uid = useId();
  const [open, setOpen] = useState(false);
  const selected = Math.max(0, options.findIndex((o) => o.value === value));
  const [active, setActive] = useState(selected);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const typed = useRef({ text: "", at: 0 });
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  useEffect(() => {
    if (open) list.current?.querySelector<HTMLElement>(`[id="${uid}-o${active}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [open, active, uid]);

  const show = () => { setActive(selected); setOpen(true); };
  const pick = (i: number) => { if (options[i]) onChange(options[i].value); setOpen(false); };
  const last = options.length - 1;

  function keys(e: KeyboardEvent<HTMLButtonElement>) {
    const k = e.key;
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(k)) { e.preventDefault(); show(); }
      return;
    }
    if (k === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(last, a + 1)); }
    else if (k === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (k === "Home") { e.preventDefault(); setActive(0); }
    else if (k === "End") { e.preventDefault(); setActive(last); }
    else if (k === "Enter" || k === " ") { e.preventDefault(); pick(active); }
    else if (k === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    else if (k === "Tab") setOpen(false);
    else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const now = Date.now();
      const t = typed.current;
      t.text = now - t.at > 700 ? k.toLowerCase() : t.text + k.toLowerCase();
      t.at = now;
      const from = t.text.length === 1 ? active + 1 : active;                 // una sola letra repetida recorre las que empiezan igual
      const order = [...options.keys()].map((_, n) => (from + n) % options.length);
      const hit = order.find((i) => options[i].label.toLowerCase().startsWith(t.text));
      if (hit !== undefined) setActive(hit);
    }
  }

  const lid = `${uid}-l`;
  const bid = `${uid}-b`;
  return (
    <div className={`selectfield${inline ? " inline" : ""}`} ref={root}>
      {label && <span className="sf-label" id={lid}>{label}</span>}
      <div className="sf-box">
      <button type="button" id={bid} className="sf-btn" role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-controls={`${uid}-list`}
        aria-activedescendant={open ? `${uid}-o${active}` : undefined}
        aria-labelledby={label ? `${lid} ${bid}` : undefined} aria-label={label ? undefined : ariaLabel}
        onClick={() => (open ? setOpen(false) : show())} onKeyDown={keys}>
        <span className="sf-value">{current?.label ?? ""}</span>
        <span className="sf-chev" aria-hidden="true" />
      </button>
      {open && (
        <ul className="sf-list" role="listbox" id={`${uid}-list`} ref={list} aria-labelledby={label ? lid : undefined} aria-label={label ? undefined : ariaLabel}>
          {options.map((o, i) => (
            <li key={o.value} id={`${uid}-o${i}`} role="option" aria-selected={o.value === value}
              className={`${i === active ? "act" : ""}${o.value === value ? " sel" : ""}`}
              onPointerEnter={() => setActive(i)} onPointerDown={(e) => e.preventDefault()} onClick={() => pick(i)}>
              {o.label}
            </li>
          ))}
        </ul>
      )}
      </div>
    </div>
  );
}
