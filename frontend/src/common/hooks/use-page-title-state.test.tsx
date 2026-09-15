import { cleanup, render } from "@testing-library/react";
import { PageTitleStateContext, usePageTitleState } from "./use-page-title-state";

afterEach(cleanup);

function PageState({ label }: { label?: string }) {
  usePageTitleState(label);
  return null;
}

it("declares a state for the current location and removes it on unmount", () => {
  const remove = vi.fn();
  const report = vi.fn(() => remove);
  const { unmount } = render(
    <PageTitleStateContext.Provider value={{ locationKey: "current", report }}>
      <PageState label="Access Denied" />
    </PageTitleStateContext.Provider>,
  );
  expect(report).toHaveBeenCalledWith("current", "Access Denied");
  unmount();
  expect(remove).toHaveBeenCalledOnce();
});

it("does not write a title outside the owner or for an absent state", () => {
  const previous = document.title;
  const { rerender } = render(<PageState label="Access Denied" />);
  const report = vi.fn();
  rerender(
    <PageTitleStateContext.Provider value={{ locationKey: "current", report }}>
      <PageState />
    </PageTitleStateContext.Provider>,
  );
  expect(report).not.toHaveBeenCalled();
  expect(document.title).toBe(previous);
});
