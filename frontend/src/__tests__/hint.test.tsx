import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Hint from "../components/Hint";

describe("Hint", () => {
  it("explica al pasar el ratón y se esconde al salir", () => {
    render(<Hint label="Cómo funciona">texto de ayuda</Hint>);
    const btn = screen.getByRole("button", { name: "Cómo funciona" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.mouseEnter(btn.parentElement!);
    expect(screen.getByRole("tooltip")).toHaveTextContent("texto de ayuda");
    expect(btn).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
    fireEvent.mouseLeave(btn.parentElement!);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("se queda abierto al pulsarlo (móvil) y Esc lo cierra", () => {
    render(<Hint label="Cómo funciona">texto de ayuda</Hint>);
    const btn = screen.getByRole("button", { name: "Cómo funciona" });
    fireEvent.click(btn);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.keyDown(btn, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
