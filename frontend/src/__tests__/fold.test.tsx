import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { Section } from "../components/ui";

const details = (c: HTMLElement) => c.querySelector("details")!;

describe("secciones plegables", () => {
  beforeEach(() => { localStorage.clear(); history.replaceState(null, "", "/"); });

  it("empiezan como se les dice y enseñan el resumen solo cuando están cerradas", () => {
    const { container } = render(<Section id="uno" fold="closed" hint="resumen corto" title="Uno"><p>dentro</p></Section>);
    expect(details(container).open).toBe(false);
    expect(screen.getByText("resumen corto")).toBeInTheDocument();
    const d = details(container);
    d.open = true;
    fireEvent(d, new Event("toggle"));
    expect(screen.queryByText("resumen corto")).toBeNull();
  });

  it("un enlace con #id la abre aunque empiece cerrada", () => {
    history.replaceState(null, "", "/#dos");
    const { container } = render(<Section id="dos" fold="closed" title="Dos"><p>dentro</p></Section>);
    expect(details(container).open).toBe(true);
  });

  it("se acuerda de lo que el usuario dejó abierto o cerrado", () => {
    const first = render(<Section id="tres" fold="closed" title="Tres"><p>dentro</p></Section>);
    const d = details(first.container);
    d.open = true;
    fireEvent(d, new Event("toggle"));
    first.unmount();
    const again = render(<Section id="tres" fold="closed" title="Tres"><p>dentro</p></Section>);
    expect(details(again.container).open).toBe(true);
  });

  it("no confunde lo que se abre solo con una elección del usuario", () => {
    const { container } = render(<Section id="cinco" fold="open" title="Cinco"><p>dentro</p></Section>);
    fireEvent(details(container), new Event("toggle"));        // el navegador lo dispara al montar
    expect(localStorage.getItem("fold:/#cinco")).toBeNull();
  });

  it("sin «fold» sigue siendo una sección normal", () => {
    const { container } = render(<Section id="cuatro" title="Cuatro"><p>dentro</p></Section>);
    expect(container.querySelector("details")).toBeNull();
  });
});
