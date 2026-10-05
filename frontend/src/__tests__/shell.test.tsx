import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Shell } from "../components/Shell";
import { BRAND, pageTitle } from "../lib/brand";

function mockSession(logged: boolean, pending = 0) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).split("?")[0];
    const body = path === "/api/session"
      ? { login_enabled: true, logged_in: logged, login: logged ? "u13" : null, name: logged ? "Ana" : null }
      : path === "/api/help/summary" ? { incoming: pending, offers: 0, to_confirm: 0, total: pending } : {};
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
}

const sections = [{ href: "#resumen", label: "Resumen" }, { href: "#ritmo", label: "Ritmo" }];
const page = () => render(<Shell sub="campus" links={sections} current="#ritmo"><main>contenido</main></Shell>);

afterEach(() => vi.unstubAllGlobals());

describe("cabecera mínima", () => {
  it("lleva el nombre de la web y no «42 Madrid»", async () => {
    mockSession(true);
    page();
    await userEvent.click(await screen.findByRole("button", { name: "Menú" }));                // el nombre vive dentro del menú
    expect(await screen.findByRole("link", { name: new RegExp(BRAND) })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/42 Madrid/);
    expect(pageTitle("Mi panel")).toBe(`Mi panel · ${BRAND}`);
  });

  it("con sesión solo muestra el botón de menú y lo demás está dentro", async () => {
    mockSession(true);
    page();
    const btn = await screen.findByRole("button", { name: "Menú" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Mi panel" })).toBeNull();                 // nada de enlaces sueltos en la barra
    await userEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    for (const name of ["Mi panel", "Ayuda entre alumnos", "Estadísticas del campus", "Resumen", "Ritmo", "Salir"]) {
      expect(screen.getByRole("link", { name: new RegExp(name) })).toBeInTheDocument();
    }
    expect(screen.getByText(/Hola,/)).toHaveTextContent("Ana");
    expect(screen.getByRole("link", { name: "Ritmo" })).toHaveAttribute("aria-current", "true");     // la sección visible va marcada
    expect(screen.getByRole("link", { name: "Salir" })).toHaveAttribute("href", "/auth/logout");
    expect(screen.getByRole("button", { name: /Tema/ })).toBeInTheDocument();
  });

  it("Escape lo cierra y devuelve el foco al botón", async () => {
    mockSession(true);
    page();
    const btn = await screen.findByRole("button", { name: "Menú" });
    await userEvent.click(btn);
    expect(screen.getByRole("navigation", { name: "Navegación" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("navigation", { name: "Navegación" })).toBeNull());
    expect(btn).toHaveFocus();
  });

  it("pulsar fuera lo cierra, pero pulsar dentro no", async () => {
    mockSession(true);
    const { container } = page();
    await userEvent.click(await screen.findByRole("button", { name: "Menú" }));
    fireEvent.pointerDown(screen.getByText(/Hola,/));
    expect(screen.getByRole("navigation", { name: "Navegación" })).toBeInTheDocument();
    fireEvent.pointerDown(container.querySelector("main")!);
    await waitFor(() => expect(screen.queryByRole("navigation", { name: "Navegación" })).toBeNull());
  });

  it("elegir una opción cierra el menú", async () => {
    mockSession(true);
    page();
    await userEvent.click(await screen.findByRole("button", { name: "Menú" }));
    fireEvent.click(screen.getByRole("link", { name: "Resumen" }));
    await waitFor(() => expect(screen.queryByRole("navigation", { name: "Navegación" })).toBeNull());
  });

  it("avisa con un punto en el botón cuando hay cosas pendientes en Ayuda y con el número dentro", async () => {
    mockSession(true, 3);
    page();
    const dot = await screen.findByLabelText("3 pendientes en Ayuda");
    expect(dot).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Menú" }));
    expect(screen.queryByLabelText("3 pendientes en Ayuda")).toBeNull();                          // abierto, el número está en la opción
    expect(screen.getByRole("link", { name: /Ayuda entre alumnos/ })).toHaveTextContent("3");
  });

  it("sin pendientes no hay punto", async () => {
    mockSession(true, 0);
    page();
    await screen.findByRole("button", { name: "Menú" });
    expect(screen.queryByLabelText(/pendientes en Ayuda/)).toBeNull();
  });

  it("sin sesión no hay menú: solo entrar con 42 y el tema", async () => {
    mockSession(false);
    page();
    expect(await screen.findByRole("link", { name: "Entrar con 42" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button", { name: "Menú" })).toBeNull();
    expect(screen.getByRole("button", { name: /Tema/ })).toBeInTheDocument();
  });
});
