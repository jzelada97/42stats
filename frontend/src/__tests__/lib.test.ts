import { routeFor } from "../App";
import { completeMonths, currentMonth, fmt, fmt1, monthLabel, pct, plural } from "../lib/format";
import { hostOf, internalPath, profileUrl, safeUrl } from "../lib/safe";
import { nextMode, readMode } from "../lib/theme";
import { niceMax } from "../components/charts/Columns";

describe("safeUrl", () => {
  it.each([
    "http://example.com/x", "javascript:alert(1)", "data:text/html,<script>1</script>", "ftp://example.com/x",
    "https://user:pass@example.com/", "https://127.0.0.1/x", "https://127.1/", "https://0x7f.1/", "https://0177.0.0.1/",
    "https://[::1]/x", "https://10.0.0.5/", "https://sinpunto/x", "//example.com/x", "", "no es una url",
  ])("rechaza %s", (u) => expect(safeUrl(u)).toBe(""));

  it("acepta https públicos y los normaliza", () => {
    expect(safeUrl("https://docs.python.org/3/library/re.html")).toBe("https://docs.python.org/3/library/re.html");
    expect(safeUrl("https://xn--bcher-kva.example/x")).toMatch(/^https:\/\/xn--bcher-kva\.example/);
  });

  it("no se deja engañar por barras invertidas: el destino real es el que el navegador parsea", () => {
    expect(hostOf("https://evil.tk\\.docs.python.org/")).toBe("evil.tk");        // lo que abriría el navegador
  });

  it("null y undefined no son enlaces", () => {
    expect(safeUrl(null)).toBe("");
    expect(safeUrl(undefined)).toBe("");
  });
});

describe("profileUrl e internalPath", () => {
  it("solo logins de 42 válidos", () => {
    expect(profileUrl("ana-42-")).toBe("https://profile.intra.42.fr/users/ana-42-");
    for (const bad of ["", "a", "x/../y", "a b", "<img>", "javascript:1", "a".repeat(40)]) expect(profileUrl(bad)).toBe("");
    expect(profileUrl(null)).toBe("");
  });
  it("las rutas internas no pueden salir del sitio", () => {
    expect(internalPath("/ayuda?project=3")).toBe("/ayuda?project=3");
    expect(internalPath("//otro.sitio")).toBe("/");
    expect(internalPath("https://otro.sitio")).toBe("/");
  });
});

describe("formato", () => {
  it("números, porcentajes y meses en español", () => {
    expect(fmt(1234567)).toBe("1.234.567");
    expect(fmt(null)).toBe("–");
    expect(fmt1(2.34)).toBe("2,3");
    expect(pct(0.456)).toBe("46 %");
    expect(pct(undefined)).toBe("–");
    expect(monthLabel("2026-03")).toBe("mar 26");
    expect(plural(1, "punto", "puntos")).toBe("1 punto");
    expect(plural(3, "punto", "puntos")).toBe("3 puntos");
  });
  it("el mes en curso no cuenta en las series", () => {
    const rows = [{ month: "2020-01" }, { month: currentMonth() }];
    expect(completeMonths(rows)).toEqual([{ month: "2020-01" }]);
  });
  it("niceMax redondea hacia una escala legible", () => {
    expect([0, 0.7, 3, 7, 130, 4200].map(niceMax)).toEqual([1, 1, 5, 10, 200, 5000]);
  });
});

describe("tema", () => {
  afterEach(() => localStorage.clear());
  it("rota auto, claro y oscuro", () => {
    expect(nextMode("auto")).toBe("light");
    expect(nextMode("light")).toBe("dark");
    expect(nextMode("dark")).toBe("auto");
  });
  it("lee el tema guardado y tolera valores raros", () => {
    expect(readMode()).toBe("auto");
    localStorage.setItem("theme", "dark");
    expect(readMode()).toBe("dark");
    localStorage.setItem("theme", "<script>");
    expect(readMode()).toBe("auto");
  });
});

describe("rutas", () => {
  it("cada ruta del servidor lleva a su página", () => {
    expect(routeFor("/me")).toBe("me");
    expect(routeFor("/me/")).toBe("me");
    expect(routeFor("/ayuda")).toBe("ayuda");
    expect(routeFor("/campus")).toBe("campus");
    expect(routeFor("/login")).toBe("login");
    expect(routeFor("/")).toBe("login");
    expect(routeFor("/cualquier/otra")).toBe("login");
  });
});
