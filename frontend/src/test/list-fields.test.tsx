import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { CorrectionDialog } from "@/components/CorrectionDialog";
import { ListFieldValue } from "@/components/review/ListFieldValue";
import { type FieldScope, ReviewFieldPanel } from "@/components/review/ReviewFieldPanel";
import { testField } from "@/test/fixtures";

const span = (unitIndex: number) => ({
  id: `span-${unitIndex}`,
  unit_index: unitIndex,
  unit_kind: "page",
  text: "Evidence",
  polygon: [0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2],
  word_ids: [],
  cell_range: "",
  mapping_method: "exact",
  match_score: 1,
  offset_start: null,
  offset_end: null,
});

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
      scope="all"
      currentUnit={0}
      selectedField={null}
      activeRun="run"
      documentFailed={false}
      canReview={true}
      canApprove={false}
      onSelect={select}
      onScopeChange={() => {}}
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

it("groups review decisions, marks the current choice, and separates ground-truth promotion", () => {
  render(
    <ReviewFieldPanel
      fields={[
        {
          ...testField(),
          field_type: "list",
          raw_value: '[{"amount":"100"}]',
          review_status: "accepted",
          validation_status: "warning",
          validation_messages: [
            "Verify every list entry and its row associations against the document; automatic list verification is not available.",
          ],
        },
      ]}
      scope="all"
      currentUnit={0}
      selectedField={null}
      activeRun="run"
      documentFailed={false}
      canReview={true}
      canApprove={true}
      onSelect={() => {}}
      onScopeChange={() => {}}
      onClearSelection={() => {}}
      onAction={() => {}}
      onCorrect={() => {}}
    />,
  );

  expect(screen.getByRole("group", { name: "Change review decision" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Accept value" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Correct value" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByText("Review needed")).toBeVisible();
  expect(
    screen.getByText("Check each row against the document. Automated verification isn't available for list fields."),
  ).toBeVisible();
  expect(screen.getByText("Use this reviewed value as the expected answer in evaluations.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Promote to ground truth" })).toBeVisible();
});

it("defaults to document-wide review work while offering page and all-field scopes", () => {
  const fields = [
    testField({ id: "current", name: "current_flag", raw_value: "Current flag", spans: [span(0)] }),
    testField({ id: "other", name: "other_flag", raw_value: "Other page flag", spans: [span(1)] }),
    testField({ id: "unlocated", name: "unlocated_flag", raw_value: "Unlocated flag", spans: [] }),
    testField({
      id: "accepted",
      name: "accepted_field",
      raw_value: "Accepted value",
      review_status: "accepted",
      spans: [span(0)],
    }),
  ];

  function ScopedPanel() {
    const [scope, setScope] = useState<FieldScope>("review");
    return (
      <ReviewFieldPanel
        fields={fields}
        scope={scope}
        currentUnit={0}
        selectedField={null}
        activeRun="run"
        documentFailed={false}
        canReview={true}
        canApprove={false}
        onSelect={() => {}}
        onScopeChange={setScope}
        onClearSelection={() => {}}
        onAction={() => {}}
        onCorrect={() => {}}
      />
    );
  }

  render(<ScopedPanel />);

  expect(screen.getByRole("button", { name: "Needs review 3" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "This page 2" })).toBeVisible();
  expect(screen.getByRole("button", { name: "All 4" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "On page 1" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Other pages" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "No source location" })).toBeVisible();
  expect(screen.getByText("Current flag")).toBeVisible();
  expect(screen.getByText("Other page flag")).toBeVisible();
  expect(screen.getByText("Unlocated flag")).toBeVisible();
  expect(screen.queryByText("Accepted value")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "This page 2" }));
  expect(screen.getByText("Current flag")).toBeVisible();
  expect(screen.getByText("Accepted value")).toBeVisible();
  expect(screen.queryByText("Other page flag")).not.toBeInTheDocument();
  expect(screen.queryByText("Unlocated flag")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "All 4" }));
  expect(screen.getByText("Current flag")).toBeVisible();
  expect(screen.getByText("Other page flag")).toBeVisible();
  expect(screen.getByText("Unlocated flag")).toBeVisible();
  expect(screen.getByText("Accepted value")).toBeVisible();
});

it("aligns an activated field below the header when the document viewer is sticky", () => {
  const scrollIntoView = vi.fn();
  const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollIntoView,
  });
  const readStyle = window.getComputedStyle.bind(window);
  const computedStyle = vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudoElement) => {
    const style = readStyle(element, pseudoElement);
    if (element.classList.contains("review-document-pane")) style.position = "sticky";
    return style;
  });

  try {
    render(
      <div>
        <div className="review-document-pane" />
        <ReviewFieldPanel
          fields={[testField()]}
          scope="all"
          currentUnit={0}
          selectedField={null}
          activeRun="run"
          documentFailed={false}
          canReview={false}
          canApprove={false}
          onSelect={() => {}}
          onScopeChange={() => {}}
          onClearSelection={() => {}}
          onAction={() => {}}
          onCorrect={() => {}}
        />
      </div>,
    );

    fireEvent.click(screen.getByRole("button", { name: `${testField().name} ${testField().raw_value}` }));
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start", inline: "nearest" });
  } finally {
    computedStyle.mockRestore();
    if (originalScrollIntoView) {
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScrollIntoView);
    } else {
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  }
});
