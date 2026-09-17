import { screen } from "@testing-library/react";
import { DocumentNavigation } from "@/components/review/DocumentNavigation";
import { renderWithApp } from "@/test/test-utils";

it("browses the dataset without retaining a run or a previous document's field selection", () => {
  renderWithApp(
    <DocumentNavigation
      navigation={{
        scope: "dataset",
        run: null,
        previous: null,
        next: { id: "next", original_filename: "next.pdf" },
      }}
      searchParams={new URLSearchParams("from=datasets&field=old&run=old&group_page=2")}
    />,
  );
  expect(screen.getByRole("link", { name: "Next document: next.pdf" })).toHaveAttribute(
    "href",
    "/documents/next?from=datasets",
  );
  expect(screen.getByRole("button", { name: "Previous document" })).toBeDisabled();
  expect(screen.getByText("Documents in this dataset · Newest uploads first")).toBeVisible();
});

it("explains a single-document run without offering circular navigation", () => {
  renderWithApp(
    <DocumentNavigation
      navigation={{ scope: "run", run: "run-1", previous: null, next: null }}
      searchParams={new URLSearchParams()}
    />,
  );
  expect(screen.getByRole("button", { name: "Previous document" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Next document" })).toBeDisabled();
  expect(screen.getByText("Only document in this run")).toBeVisible();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
