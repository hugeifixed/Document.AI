import { screen } from "@testing-library/react";
import { JourneyCue } from "@/components/JourneyCue";
import { renderWithApp } from "@/test/test-utils";

describe("JourneyCue", () => {
  it("scrolls and focuses an in-page target even when its hash is already active", async () => {
    const scrollIntoView = vi.fn();
    const target = document.createElement("div");
    target.id = "run-items";
    target.tabIndex = -1;
    target.scrollIntoView = scrollIntoView;
    document.body.append(target);

    const { user } = renderWithApp(
      <JourneyCue
        action={{
          title: "1 document did not complete",
          description: "Inspect the failure.",
          label: "View failed documents",
          to: "#run-items",
        }}
      />,
      { route: "/runs/run-1#run-items" },
    );

    await user.click(screen.getByRole("link", { name: "View failed documents" }));

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(target).toHaveFocus();
    target.remove();
  });
});
