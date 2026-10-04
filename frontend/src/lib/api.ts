import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function message(data: unknown, status: number): string {
  const d = (data as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return "Revisa los campos del formulario.";
  return `error ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (r.status === 401) {
    location.replace("/login");
    throw new ApiError("sesión necesaria", 401);
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(message(data, r.status), r.status);
  return data as T;
}

export const get = <T = any>(path: string): Promise<T> => request<T>(path);

export const post = <T = any>(path: string, body: unknown = {}): Promise<T> =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export interface Session {
  login_enabled: boolean;
  logged_in: boolean;
  login: string | null;
  name: string | null;
}

export type Loadable<T> = { data: T | null; error: string | null; loading: boolean; reload: () => Promise<void> };

/** Carga un recurso al montar. Un 401 redirige al login (lo hace `get`). */
export function useLoad<T>(path: string | null): Loadable<T> {
  const [state, set] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: path !== null });
  const reload = useCallback(async () => {
    if (path === null) return;
    try {
      set({ data: await get<T>(path), error: null, loading: false });
    } catch (e) {
      set((s) => ({ data: s.data, error: (e as Error).message, loading: false }));
    }
  }, [path]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { ...state, reload };
}

export function useSession(): Session | null {
  const [s, set] = useState<Session | null>(null);
  useEffect(() => {
    fetch("/api/session").then((r) => r.json()).then(set).catch(() => undefined);
  }, []);
  return s;
}
