import { useEffect, useRef, useState } from "react";

/** Ancho del contenedor en px. Por debajo de 160 px el layout aún no está listo (o el panel está colapsado): se espera. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => {
      const n = Math.floor(el.clientWidth);
      if (n >= 160) setW((old) => (old === n ? old : n));
    };
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}
