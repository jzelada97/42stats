import { useEffect, useState } from "react";

export type Mode = "auto" | "light" | "dark";
const MODES: Mode[] = ["auto", "light", "dark"];

export function readMode(): Mode {
  try {
    const v = localStorage.getItem("theme");
    return v === "light" || v === "dark" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function applyMode(mode: Mode): void {
  if (mode === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", mode);
}

export function nextMode(mode: Mode): Mode {
  return MODES[(MODES.indexOf(mode) + 1) % MODES.length];
}

export function useTheme(): [Mode, () => void] {
  const [mode, setMode] = useState<Mode>(readMode);
  useEffect(() => applyMode(mode), [mode]);
  const cycle = () => {
    const m = nextMode(mode);
    try {
      localStorage.setItem("theme", m);
    } catch {
      /* sin almacenamiento: vale solo para esta visita */
    }
    setMode(m);
  };
  return [mode, cycle];
}
