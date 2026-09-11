import { screen, waitFor } from "@testing-library/react";
import { Projects } from "@/pages/Projects";
import { renderWithApp } from "@/test/test-utils";
import { useWorkingContext } from "@/workspace/context";

const { postProject } = vi.hoisted(() => ({
  postProject: vi.fn(),
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: ["docai_operators"] } }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  list: vi.fn().mockResolvedValue({ count: 0, page: 1, page_size: 25, total_pages: 0, results: [] }),
  post: postProject,
  tableParams: vi.fn().mockReturnValue({}),
}));

describe("Projects", () => {
  beforeEach(() => {
    postProject.mockReset();
    useWorkingContext.getState().clear();
  });

  it("generates a slug from the name and preserves a custom edit", async () => {
    postProject.mockResolvedValue({
      id: "1",
      name: "Commercial Lending",
      slug: "custom-lending",
      description: "",
      created: "2026-09-10T00:00:00Z",
    });
    const { user } = renderWithApp(<Projects />);

    const name = screen.getByLabelText(/^Name/);
    const slug = screen.getByLabelText("Slug") as HTMLInputElement;

    await user.type(name, "Commercial Loan Onboarding");
    expect(slug).toHaveValue("commercial-loan-onboarding");

    await user.clear(slug);
    await user.type(slug, "custom-lending");
    await user.clear(name);
    await user.type(name, "Commercial Lending");
    expect(slug).toHaveValue("custom-lending");

    await user.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() =>
      expect(postProject).toHaveBeenCalledWith("/projects/", {
        name: "Commercial Lending",
        slug: "custom-lending",
        description: "",
      }),
    );
    await waitFor(() => expect(name).toHaveValue(""));
    expect(useWorkingContext.getState()).toMatchObject({ projectId: "1", datasetId: null });
  });
});
