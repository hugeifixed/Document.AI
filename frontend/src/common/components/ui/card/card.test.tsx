import { render, screen } from "@testing-library/react";
import { Card } from "./card";
it("preserves accessible shared behavior", () => { render(<Card title="Summary">Content</Card>); expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible(); expect(screen.getByText("Content")).toBeVisible(); });
