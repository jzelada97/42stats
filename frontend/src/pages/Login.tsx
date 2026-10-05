import { Seigaiha } from "../components/charts/Decor";
import { Shell } from "../components/Shell";
import { useSession } from "../lib/api";

export const LOGIN_ERRORS: Record<string, string> = {
  denegado: "Cancelaste el acceso en 42. Puedes volver a intentarlo cuando quieras.",
  estado: "El acceso no se pudo completar (caducó, se repitió o tu navegador bloquea las cookies). Vuelve a pulsar «Entrar con 42» una sola vez y sin abrir otra pestaña.",
  intercambio: "42 no confirmó tu acceso. Inténtalo de nuevo en un minuto.",
  limite: "Demasiados intentos seguidos. Espera un minuto y vuelve a probar.",
  "fuera-de-campus": "Tu cuenta no está en los datos del campus de Madrid, así que no hay panel que mostrar.",
};

export function errorFor(code: string | null): string | null {
  return code ? LOGIN_ERRORS[code] ?? "No se pudo completar el acceso." : null;
}

export default function Login() {
  const session = useSession();
  const error = errorFor(new URLSearchParams(location.search).get("error"));
  const disabled = session !== null && !session.login_enabled;
  if (session?.logged_in && !error) location.replace("/me");
  return (
    <Shell sub="campus Madrid" links={[]} showAuth={false}>
      <main className="login-wrap">
        <section className="card raise login-card" aria-labelledby="h-login">
          <Seigaiha />
          <div className="kicker">estadísticas del campus</div>
          <h1 id="h-login">Tu panel personal</h1>
          <p className="lead">Entra con tu cuenta de 42 y verás cómo vas frente a tu promoción, con consejos para la semana.</p>

          {error && <div className="login-error" role="alert">{error}</div>}

          <div className="row">
            <a className="btn" href={disabled ? undefined : "/auth/login"} aria-disabled={disabled ? "true" : undefined}>Entrar con 42</a>
          </div>
          {disabled && <p className="sub">El login todavía no está activado en este servidor.</p>}

          <ul className="login-points">
            <li><b>Qué verás:</b> tu rank y tus milestones, cuánto llevas sin validar uno, tu actividad en el campus y cómo estás frente a tu cursus.</li>
            <li><b>Qué usamos:</b> solo tu perfil público de 42 (permiso <span className="mono">public</span>). No pedimos tu contraseña: la escribes en 42, no aquí.</li>
            <li><b>Qué guardamos:</b> una cookie de sesión con tu login. <b>No guardamos tu token.</b> Si indicas tu deadline o tu freeze, esas fechas se asocian a tu cuenta y puedes borrarlas cuando quieras. Solo tú ves tus datos.</li>
            <li><b>Qué no vemos:</b> tu deadline de milestone y tu freeze no están en la API pública de 42. Si quieres que cuenten en el análisis, los indicas tú.</li>
          </ul>
        </section>
      </main>
    </Shell>
  );
}
