import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode, type PointerEvent } from "react";

interface TipState {
  x: number;
  y: number;
  content: ReactNode;
}
interface TipApi {
  show: (e: PointerEvent | { clientX: number; clientY: number }, content: ReactNode) => void;
  hide: () => void;
}

const TipContext = createContext<TipApi>({ show: () => undefined, hide: () => undefined });
export const useTip = (): TipApi => useContext(TipContext);

/** Un único tooltip para toda la página, siempre dentro de la ventana. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TipState | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const show = useCallback<TipApi["show"]>((e, content) => setTip({ x: e.clientX, y: e.clientY, content }), []);
  const hide = useCallback(() => setTip(null), []);

  useEffect(() => {
    addEventListener("scroll", hide, { passive: true });
    return () => removeEventListener("scroll", hide);
  }, [hide]);

  useEffect(() => {
    const el = box.current;
    if (!el || !tip) return;
    const r = el.getBoundingClientRect();
    let x = tip.x + 14;
    let y = tip.y + 14;
    if (x + r.width > innerWidth - 8) x = tip.x - r.width - 14;
    if (y + r.height > innerHeight - 8) y = tip.y - r.height - 14;
    el.style.left = Math.max(8, x) + "px";
    el.style.top = Math.max(8, y) + "px";
  }, [tip]);

  return (
    <TipContext.Provider value={{ show, hide }}>
      {children}
      <div ref={box} className="tip" role="tooltip" data-open={tip ? "1" : "0"}>
        {tip?.content}
      </div>
    </TipContext.Provider>
  );
}
