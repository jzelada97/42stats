import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import Select from "../components/Select";

const OPTS = [{ value: "", label: "General" }, { value: "1", label: "libft" }, { value: "2", label: "get_next_line" }, { value: "3", label: "ft_printf" }];

function Harness() {
  const [v, set] = useState("");
  return <><Select label="Proyecto" value={v} options={OPTS} onChange={set} /><output data-testid="v">{v}</output></>;
}

describe("Select", () => {
  it("enseña la opción elegida y las demás al abrir, y elige con el ratón", () => {
    render(<Harness />);
    const box = screen.getByRole("combobox", { name: /Proyecto/ });
    expect(box).toHaveTextContent("General");
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.click(box);
    expect(screen.getAllByRole("option")).toHaveLength(4);
    fireEvent.click(screen.getByRole("option", { name: "get_next_line" }));
    expect(screen.getByTestId("v")).toHaveTextContent("2");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(box).toHaveTextContent("get_next_line");
  });

  it("se maneja con el teclado: flechas, Intro, escribir la inicial y Esc", () => {
    render(<Harness />);
    const box = screen.getByRole("combobox", { name: /Proyecto/ });
    fireEvent.keyDown(box, { key: "ArrowDown" });                       // abre
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(box).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: "get_next_line" }).id);
    fireEvent.keyDown(box, { key: "Enter" });
    expect(screen.getByTestId("v")).toHaveTextContent("2");

    fireEvent.keyDown(box, { key: " " });                               // abre de nuevo y busca por inicial
    fireEvent.keyDown(box, { key: "f" });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(screen.getByTestId("v")).toHaveTextContent("3");

    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByTestId("v")).toHaveTextContent("3");             // Esc no cambia nada
  });

  it("sin etiqueta visible usa aria-label", () => {
    render(<Select ariaLabel="¿Te ayudó alguien?" value="" options={OPTS} onChange={() => {}} />);
    expect(screen.getByRole("combobox", { name: "¿Te ayudó alguien?" })).toBeInTheDocument();
  });
});
