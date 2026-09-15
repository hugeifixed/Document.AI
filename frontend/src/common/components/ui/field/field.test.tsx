import { render, screen } from "@testing-library/react";
import { Field } from "./field";
it("associates its visible label and required marker with a control", () => {
  render(<Field id="name" label="Name" required labelAction={<button>Help</button>}><input id="name" required /></Field>);
  expect(screen.getByRole("textbox", { name: "Name" })).toBeRequired();
  expect(screen.getByRole("button", { name: "Help" })).toBeVisible();
  expect(screen.getByText("*")).toHaveAttribute("aria-hidden", "true");
});
