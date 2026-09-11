import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FileNameLink } from "@/components/FileNameLink";

describe("FileNameLink", () => {
  it("keeps the full filename accessible while rendering its extension separately", () => {
    const name = "a-very-long-generated-document-name.pdf";
    render(
      <MemoryRouter>
        <FileNameLink name={name} to="/review/document-1" />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name });
    expect(link).toHaveAttribute("href", "/review/document-1");
    expect(link).toHaveAttribute("title", name);
    expect(screen.getByText("a-very-long-generated-document-name")).toBeInTheDocument();
    expect(screen.getByText(".pdf")).toBeInTheDocument();
  });
});
