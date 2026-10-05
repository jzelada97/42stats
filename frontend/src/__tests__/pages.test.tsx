import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Ayuda from "../pages/Ayuda";
import Login, { errorFor } from "../pages/Login";
import { Enso } from "../components/charts/Decor";

const HOSTILE = `<img src=x onerror="window.__pwned=1"> <script>window.__pwned=1</script>`;

const overview = {
  is_admin: false,
  projects: [{ id: 1, name: "libft", cursus_id: 21, rank: 2 }],
  ranks: [{ id: 2, name: "Rank 02", projects: 1 }],
  default_rank: 2,
  validated: [{ id: 1, name: "libft", mark: 100, rank: 2, in_help: true }],
  offer: { active: true, note: "", project_ids: [1] },
  requests: [{
    id: 5, project: "libft", message: HOSTILE, days: 1, mentors: [],
    responders: [{ login: "u13", points: 3, tier: "Brote" }, { login: "<b>x</b>", points: 0, tier: null }],
  }],
  incoming: [{ id: 9, login: "u15", project: "libft", message: HOSTILE, offered: false, days_waiting: 2 }],
  points: { verified: 1, pending: 1, to_confirm: 1, tier: "Brote", next: { name: "Caña", needs: 4 } },
  confirmations: [{ id: 3, project: "libft", days: 1 }],
};

function mockApi(extra: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    "/api/session": { login_enabled: true, logged_in: true, login: "u13", name: "Ana" },
    "/api/help/overview": overview,
    "/api/help/summary": { incoming: 1, offers: 1, to_confirm: 1, total: 3 },
    "/api/help/resources": { resources: [
      { id: 1, title: HOSTILE, url: "javascript:alert(1)", kind: "guía", project: "libft" },
      { id: 2, title: "Guía buena", url: "https://docs.python.org/3/", kind: "guía", project: "libft" },
    ], mine_pending: [] },
    "/api/help/mentors": { mentors: [{ login: "u14", note: HOSTILE, level: 8, mark: 100, validated_on: "2026-01-01", points: 6, tier: "Caña" }] },
    ...extra,
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).split("?")[0];
    return new Response(JSON.stringify(routes[path] ?? {}), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
}

afterEach(() => { vi.unstubAllGlobals(); delete (window as any).__pwned; });

describe("Ayuda con texto hostil de otros alumnos", () => {
  it("lo pinta como texto: sin elementos nuevos ni scripts ejecutados", async () => {
    mockApi();
    const { container } = render(<Ayuda />);
    await waitFor(() => expect(screen.getAllByText(HOSTILE, { exact: false }).length).toBeGreaterThan(0));
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")?.textContent).not.toBe("x");              // «<b>x</b>» de un login no crea negritas
    expect((window as any).__pwned).toBeUndefined();
  });

  it("los enlaces de recursos pasan por safeUrl: javascript: no es un enlace", async () => {
    mockApi();
    render(<Ayuda />);
    await waitFor(() => screen.getByText("Guía buena"));
    const good = screen.getByText("Guía buena").closest("a");
    expect(good).toHaveAttribute("href", "https://docs.python.org/3/");
    expect(good).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(good).toHaveAttribute("target", "_blank");
    const bad = screen.getAllByText(HOSTILE, { exact: false }).find((e) => e.closest("li")?.textContent?.includes("guía"));
    expect(bad?.closest("a")).toBeNull();                                          // sin href peligroso
    expect(document.querySelector('a[href^="javascript"]')).toBeNull();
  });

  it("solo hay enlaces de perfil con logins válidos", async () => {
    mockApi();
    const { container } = render(<Ayuda />);
    await waitFor(() => screen.getAllByText("u13"));
    const hrefs = [...container.querySelectorAll('a[href*="profile.intra.42.fr"]')].map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("https://profile.intra.42.fr/users/u13");
    expect(hrefs.every((h) => /^https:\/\/profile\.intra\.42\.fr\/users\/[a-z0-9_-]+$/i.test(h!))).toBe(true);
  });

  it("enseña la conexión mentor-alumno: quiero ayudar, ofrecidos y confirmaciones", async () => {
    mockApi();
    render(<Ayuda />);
    await waitFor(() => screen.getByRole("button", { name: "Quiero ayudar" }));
    expect(screen.getByText(/Agradecimientos por confirmar/)).toBeInTheDocument();
    expect(screen.getByText(/Se han ofrecido a ayudarte/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "¿Te ayudó alguien?" }));
    expect(screen.getByRole("option", { name: "Gracias a u13" })).toBeInTheDocument();
  });

  it("la tarjeta de puntos enseña el tramo, lo que falta y se explica con un «?»", async () => {
    mockApi();
    render(<Ayuda />);
    await waitFor(() => screen.getByText(/Tus puntos de mentoría/));
    expect(screen.getByText("Te faltan 4 para Caña")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /por confirmar/ })).toHaveAttribute("href", "#peticiones");
    fireEvent.click(screen.getByRole("button", { name: /Cómo funcionan los puntos/ }));
    expect(screen.getByText(/te dio las gracias al cerrarla/)).toBeInTheDocument();
  });

  it("proponer un recurso avisa de que queda registrado quién lo propone", async () => {
    mockApi();
    render(<Ayuda />);
    await waitFor(() => screen.getByText(/quedará registrada a tu nombre/));
    fireEvent.click(screen.getByRole("button", { name: "Qué se guarda de tu propuesta" }));
    expect(screen.getByText(/se sabrá quién los mandó/)).toBeInTheDocument();
  });

  it("la sección de moderación solo existe para admins", async () => {
    mockApi();
    const { container } = render(<Ayuda />);
    await waitFor(() => screen.getAllByText("u13"));
    expect(container.querySelector("#moderacion")).toBeNull();
    expect(screen.queryByText("Accesos a la web")).toBeNull();
  });
});

describe("Login", () => {
  it("traduce los códigos de error y no inventa mensajes con el texto de la URL", () => {
    expect(errorFor("estado")).toMatch(/no se pudo completar/);
    expect(errorFor("<script>alert(1)</script>")).toBe("No se pudo completar el acceso.");
    expect(errorFor(null)).toBeNull();
  });

  it("muestra el aviso cuando el login no está activado", async () => {
    mockApi({ "/api/session": { login_enabled: false, logged_in: false, login: null, name: null } });
    const { container } = render(<Login />);
    await waitFor(() => screen.getByText(/todavía no está activado/));
    const btn = container.querySelector("a.btn")!;
    expect(btn).toHaveAttribute("aria-disabled", "true");
    expect(btn).not.toHaveAttribute("href");                                         // sin destino: no se puede pulsar
  });
});

describe("Ensō", () => {
  it("se mantiene abierto aunque el progreso pase de 1 y tolera valores raros", () => {
    for (const v of [0, 0.4, 1, 3, NaN, -2]) {
      const { container, unmount } = render(<Enso value={v} label="5" caption="días" />);
      expect(container.querySelector("svg")).not.toBeNull();
      expect(container.innerHTML).not.toMatch(/NaN/);
      unmount();
    }
  });
});

describe("Avisos por correo", () => {
  it("no aparece si el servidor no tiene correo configurado", async () => {
    mockApi({ "/api/me/notify": { available: false, enabled: false, email: null } });
    const { container } = render(<Ayuda />);
    await waitFor(() => screen.getAllByText("u13"));
    expect(container.querySelector("#avisos")).toBeNull();
  });

  it("ofrece activarlos pasando por 42 y no enseña ninguna dirección", async () => {
    mockApi({ "/api/me/notify": { available: true, enabled: false, email: null } });
    const { container } = render(<Ayuda />);
    const link = await screen.findByRole("link", { name: "Activar avisos" });
    expect(link).toHaveAttribute("href", "/auth/login?purpose=notify");
    expect(container.textContent).not.toMatch(/@/);
  });

  it("si están activos enseña solo la dirección enmascarada y permite desactivarlos", async () => {
    mockApi({ "/api/me/notify": { available: true, enabled: true, email: "a***@student.42madrid.com" } });
    render(<Ayuda />);
    await waitFor(() => screen.getByText("a***@student.42madrid.com"));
    expect(screen.getByRole("button", { name: "Desactivar" })).toBeInTheDocument();
  });
});
