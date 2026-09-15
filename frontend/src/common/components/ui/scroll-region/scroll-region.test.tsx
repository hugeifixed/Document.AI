import { render, screen } from "@testing-library/react";
import { ScrollRegion } from "./scroll-region";
it("preserves accessible shared behavior", () => { render(<ScrollRegion label="Data">Rows</ScrollRegion>); expect(screen.getByRole("region", {name: "Data"})).toHaveAttribute("tabindex", "0"); });
