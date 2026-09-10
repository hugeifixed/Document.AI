import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Projects } from "@/pages/Projects";

const { postProject } = vi.hoisted(() => ({
  postProject: vi.fn(),
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: ["docai_operators"] } }),
}));

vi.mock("@/api/client", () => ({
  ApiError: class extends Error {
    errors = {};
  },
  list: vi.fn().mockResolvedValue({ count: 0, page: 1, page_size: 25, total_pages: 0, results: [] }),
  post: postProject,
  tableParams: vi.fn().mockReturnValue({}),
}));

describe("Projects", () => {
  it("generates a slug from the name and preserves a custom edit", async () => {
    postProject.mockResolvedValue({
      id: "1",
      name: "Commercial Lending",
      slug: "custom-lending",
      description: "",
      created: "2026-09-10T00:00:00Z",
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Projects />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const name = screen.getByLabelText(/^Name/);
    const slug = screen.getByLabelText("Slug") as HTMLInputElement;

    fireEvent.change(name, { target: { value: "Commercial Loan Onboarding" } });
    expect(slug).toHaveValue("commercial-loan-onboarding");

    fireEvent.change(slug, { target: { value: "custom-lending" } });
    fireEvent.change(name, { target: { value: "Commercial Lending" } });
    expect(slug).toHaveValue("custom-lending");

    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(postProject).toHaveBeenCalledWith("/projects/", {
      name: "Commercial Lending",
      slug: "custom-lending",
      description: "",
    }));
  });
});
