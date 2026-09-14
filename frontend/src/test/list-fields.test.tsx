import { fireEvent, render, screen } from "@testing-library/react";
import { CorrectionDialog } from "@/components/CorrectionDialog";
import { ListFieldValue } from "@/components/review/ListFieldValue";
import { ReviewFieldPanel } from "@/components/review/ReviewFieldPanel";
import { testField } from "@/test/fixtures";

it("shows arbitrary object keys as columns without changing literal amounts or identifiers", () => {
  render(
    <ListFieldValue
      name="entries"
      value={'[{"state":"AK","id":"001","amount":"12.30"},{"state":"DE","amount":"0.00"}]'}
    />,
  );
  expect(screen.getByRole("table", { name: "entries" })).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "state" })).toBeVisible();
  expect(screen.getByText("001")).toBeVisible();
  expect(screen.getByText("12.30")).toBeVisible();
  expect(screen.getByText("0.00")).toBeVisible();
});

it("expands simple lists without losing entries, duplicates or false values", () => {
  render(<ListFieldValue name="codes" value={'["A","A",false,"last"]'} />);
  expect(screen.queryByText("last")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show all 4 entries" }));
  expect(screen.getByText("last")).toBeVisible();
  expect(screen.getAllByText("A")).toHaveLength(2);
  expect(screen.getByText("false")).toBeVisible();
});

it("keeps malformed and masked values readable without a crash", () => {
  render(<ListFieldValue name="entries" value="[MASKED]" />);
  expect(screen.getByText("[MASKED]")).toBeVisible();
});

it("prettifies list corrections and prevents non-array submissions", () => {
  const confirm = vi.fn();
  render(
    <CorrectionDialog
      fieldName="entries"
      fieldType="list"
      initialValue='[{"amount":"12.30"}]'
      pending={false}
      onConfirm={confirm}
      onClose={() => {}}
    />,
  );
  const input = screen.getByRole("textbox", { name: "Corrected value" });
  expect(input.tagName).toBe("TEXTAREA");
  expect(input).toHaveValue('[\n  {\n    "amount": "12.30"\n  }\n]');
  fireEvent.change(input, { target: { value: '{"amount":"13.40"}' } });
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("button", { name: "Save correction" })).toBeDisabled();
  fireEvent.change(input, { target: { value: '[{"amount":"13.40"}]' } });
  fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
  expect(confirm).toHaveBeenCalledWith('[{"amount":"13.40"}]');
});

it("separates the evidence action from the collection table and makes alternatives inspectable", () => {
  const select = vi.fn();
  render(
    <ReviewFieldPanel
      fields={[
        {
          ...testField(),
          field_type: "list",
          raw_value: '[{"amount":"100"}]',
          list_candidates: [{ value: '[{"amount":"200"}]' }],
        },
      ]}
      selectedField={null}
      activeRun="run"
      documentFailed={false}
      canReview={true}
      canApprove={false}
      onSelect={select}
      onClearSelection={() => {}}
      onAction={() => {}}
      onCorrect={() => {}}
    />,
  );
  const table = screen.getByRole("table", { name: testField().name });
  expect(table.closest("button")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`${testField().name}.*1 entry`) }));
  expect(select).toHaveBeenCalledWith(testField().id);
  fireEvent.click(screen.getByText("Compare chunk alternatives (1)"));
  expect(screen.getByText("200")).toBeVisible();
});
