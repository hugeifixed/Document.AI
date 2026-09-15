import { render, screen } from "@testing-library/react";
import { PageHeader } from "./page-header";
it("preserves accessible shared behavior", () => { render(<PageHeader title="Metrics" action={<button>Refresh</button>}>Period summary</PageHeader>); expect(screen.getByRole("heading", {level: 1})).toHaveTextContent("Metrics"); expect(screen.getByRole("button", {name: "Refresh"})).toBeVisible(); });
