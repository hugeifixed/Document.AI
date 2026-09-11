import type { ColumnDef } from "@tanstack/react-table";
import { render, screen } from "@testing-library/react";
import { DataTable } from "@/components/DataTable";

const { announce } = vi.hoisted(() => ({ announce: vi.fn() }));
vi.mock("@/a11y/announce", () => ({ announce }));

type Row = { id: string; name: string };
const columns: ColumnDef<Row, unknown>[] = [{ id: "name", header: "Name", accessorKey: "name" }];
const state = { page: 1, pageSize: 25, filters: {} };

describe("DataTable", () => {
  beforeEach(() => announce.mockReset());

  it("uses a row header for the first data cell", () => {
    render(
      <DataTable
        caption="Projects"
        columns={columns}
        data={{ count: 1, page: 1, page_size: 25, total_pages: 1, results: [{ id: "1", name: "Alpha" }] }}
        state={state}
        update={() => {}}
        isLoading={false}
        getRowId={(row) => row.id}
      />,
    );
    expect(screen.getByRole("rowheader", { name: "Alpha" })).toHaveAttribute("scope", "row");
  });

  it("does not repeat live announcements when polling returns the same result summary", () => {
    const props = {
      caption: "Runs",
      columns,
      state,
      update: () => {},
      isLoading: false,
      getRowId: (row: Row) => row.id,
    };
    const { rerender } = render(
      <DataTable
        {...props}
        data={{ count: 1, page: 1, page_size: 25, total_pages: 1, results: [{ id: "1", name: "Run" }] }}
      />,
    );
    expect(announce).toHaveBeenCalledTimes(1);

    rerender(
      <DataTable
        {...props}
        data={{ count: 1, page: 1, page_size: 25, total_pages: 1, results: [{ id: "1", name: "Run" }] }}
      />,
    );
    expect(announce).toHaveBeenCalledTimes(1);

    rerender(
      <DataTable
        {...props}
        data={{ count: 2, page: 1, page_size: 25, total_pages: 1, results: [{ id: "1", name: "Run" }] }}
      />,
    );
    expect(announce).toHaveBeenCalledTimes(2);
  });
});
