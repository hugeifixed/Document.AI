import { render, screen } from "@testing-library/react";
import { SelectControl } from "./select-control";
it("preserves accessible shared behavior", () => { render(<SelectControl aria-label="Range"><option>Today</option></SelectControl>); expect(screen.getByRole("combobox", {name: "Range"})).toHaveValue("Today"); });
