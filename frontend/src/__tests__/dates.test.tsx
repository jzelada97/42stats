import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import DateField from "../components/DateField";
import { poolLabel } from "../lib/format";
import { addDays, addMonths, monthGrid, parseIso, showDate, toIso, weekday } from "../lib/dates";

describe("fechas", () => {
  it("lee y escribe aaaa-mm-dd y rechaza lo imposible", () => {
    expect(parseIso("2026-10-05")).toEqual({ y: 2026, m: 10, d: 5 });
    expect(parseIso("2026-02-30")).toBeNull();
    expect(parseIso("2026-13-01")).toBeNull();
    expect(parseIso("basura")).toBeNull();
    expect(toIso({ y: 2026, m: 3, d: 7 })).toBe("2026-03-07");
    expect(showDate("2026-10-05")).toBe("05/10/2026");
    expect(showDate("")).toBe("");
  });

  it("suma días y meses sin romperse en los extremos", () => {
    expect(addDays({ y: 2026, m: 12, d: 31 }, 1)).toEqual({ y: 2027, m: 1, d: 1 });
    expect(addMonths({ y: 2026, m: 1, d: 31 }, 1)).toEqual({ y: 2026, m: 2, d: 28 });
    expect(addMonths({ y: 2026, m: 1, d: 15 }, -1)).toEqual({ y: 2025, m: 12, d: 15 });
  });

  it("la semana empieza en lunes", () => {
    expect(weekday({ y: 2026, m: 10, d: 5 })).toBe(0);               // lunes
    const weeks = monthGrid(2026, 10);                                // 1 de octubre de 2026 cae en jueves
    expect(weeks[0].slice(0, 3)).toEqual([null, null, null]);
    expect(weeks[0][3]).toEqual({ y: 2026, m: 10, d: 1 });
    expect(weeks.flat().filter(Boolean)).toHaveLength(31);
    expect(weeks.every((w) => w.length === 7)).toBe(true);
  });

  it("la piscina se escribe con mayúscula inicial, en inglés como viene", () => {
    expect(poolLabel("april 2026")).toBe("April 2026");
    expect(poolLabel("September 2025")).toBe("September 2025");
    expect(poolLabel("2026")).toBe("2026");
  });
});

function Harness({ start = "" }: { start?: string }) {
  const [v, set] = useState(start);
  return <><DateField label="Deadline de tu milestone" value={v} onChange={set} /><output data-testid="v">{v}</output></>;
}

describe("DateField", () => {
  it("elige un día del calendario y lo devuelve en aaaa-mm-dd", () => {
    render(<Harness start="2026-10-05" />);
    expect(screen.getByRole("button", { name: /Deadline de tu milestone/ })).toHaveTextContent("05/10/2026");
    fireEvent.click(screen.getByRole("button", { name: /Deadline de tu milestone/ }));
    fireEvent.click(screen.getByRole("button", { name: "miércoles 14 de octubre de 2026" }));
    expect(screen.getByTestId("v")).toHaveTextContent("2026-10-14");
    expect(screen.queryByRole("dialog")).toBeNull();                  // se cierra al elegir
  });

  it("se mueve con el teclado y se cierra con Escape", () => {
    render(<Harness start="2026-10-05" />);
    fireEvent.click(screen.getByRole("button", { name: /Deadline de tu milestone/ }));
    const day = screen.getByRole("button", { name: "lunes 5 de octubre de 2026" });
    fireEvent.keyDown(day, { key: "ArrowDown" });
    expect(screen.getByRole("button", { name: "lunes 12 de octubre de 2026" })).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(day, { key: "PageDown" });
    expect(screen.getByText("noviembre 2026")).toBeInTheDocument();
    fireEvent.keyDown(day, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("v")).toHaveTextContent("2026-10-05");  // Escape no cambia nada
  });

  it("se puede quitar la fecha", () => {
    render(<Harness start="2026-10-05" />);
    fireEvent.click(screen.getByRole("button", { name: /Quitar/ }));
    expect(screen.getByTestId("v")).toHaveTextContent("");
    expect(screen.getByRole("button", { name: /Deadline de tu milestone/ })).toHaveTextContent("dd/mm/aaaa");
  });
});
