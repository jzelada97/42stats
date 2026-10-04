/** Solo https público y sin credenciales: los enlaces que escribe otro alumno nunca se pintan sin pasar por aquí. */
export function safeUrl(u: string | null | undefined): string {
  try {
    const x = new URL(String(u));
    // Nada de IPs (127.1, 0x7f.1...), IPv6 ni hosts sin letras en el último tramo: no son dominios de nadie.
    const host = x.hostname;
    if (x.protocol !== "https:" || x.username || x.password || host.includes(":") || !/\.([a-z]{2,63}|xn--[a-z0-9-]+)$/i.test(host)) return "";
    return x.href;
  } catch {
    return "";
  }
}

const LOGIN_RE = /^[a-z0-9][a-z0-9_-]{1,29}$/i;
export const profileUrl = (login: string | null | undefined): string =>
  LOGIN_RE.test(login ?? "") ? `https://profile.intra.42.fr/users/${login}` : "";

/** Un destino interno: ruta absoluta del propio sitio, nunca //otro-sitio ni esquemas. */
export const internalPath = (p: string): string => (p.startsWith("/") && !p.startsWith("//") ? p : "/");

/** Dominio real que abriría el navegador (para que un admin decida mirando el destino, no el texto). */
export const hostOf = (u: string): string => {
  try {
    return new URL(u).hostname;
  } catch {
    return "?";
  }
};
