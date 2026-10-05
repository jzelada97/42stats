import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** Un «?» que explica algo: se abre al pasar el ratón, al enfocarlo con el teclado o al pulsarlo (móvil); Esc lo cierra. */
export default function Hint({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [focused, setFocused] = useState(false);
  const open = hover || pinned || focused;
  const pop = useRef<HTMLSpanElement>(null);
  const [flip, setFlip] = useState(false);                       // si no cabe por la derecha, se abre hacia la izquierda

  useLayoutEffect(() => {
    if (!open) { setFlip(false); return; }
    const r = pop.current?.getBoundingClientRect();
    if (r && r.right > window.innerWidth - 12) setFlip(true);
  }, [open]);

  useEffect(() => {
    if (!pinned) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setPinned(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [pinned]);

  return (
    <span className="hint" ref={root} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <button type="button" className="hint-btn" aria-label={label} aria-expanded={open} aria-describedby={open ? id : undefined}
        onClick={() => setPinned((p) => !p)}
        onFocus={(e) => { try { setFocused(e.currentTarget.matches(":focus-visible")); } catch { setFocused(false); } }}
        onBlur={() => setFocused(false)}
        onKeyDown={(e) => { if (e.key === "Escape") { setPinned(false); setHover(false); setFocused(false); } }}>
        ?
      </button>
      {open && <span className={`hint-pop${flip ? " flip" : ""}`} role="tooltip" id={id} ref={pop}>{children}</span>}
    </span>
  );
}
