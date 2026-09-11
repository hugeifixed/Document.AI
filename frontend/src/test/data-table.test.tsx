import type { ColumnDef } from "@tanstack/react-table";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("sorts, changes page size, and resets pagination through accessible controls", async () => {
    const user = userEvent.setup();
    const update = vi.fn();
    const data = {
      count: 40,
      page: 2,
      page_size: 25,
      total_pages: 2,
      results: [{ id: "1", name: "Alpha" }],
    };
    const { rerender } = render(
      <DataTable
        caption="Projects"
        columns={columns}
        data={data}
        state={{ ...state, page: 2 }}
        update={update}
        isLoading={false}
        getRowId={(row) => row.id}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(update).toHaveBeenLastCalledWith({ sort: "name", desc: false, page: 1 });

    rerender(
      <DataTable
        caption="Projects"
        columns={columns}
        data={data}
        state={{ ...state, page: 2, sort: "name", desc: false }}
        update={update}
        isLoading={false}
        getRowId={(row) => row.id}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(update).toHaveBeenLastCalledWith({ sort: "name", desc: true, page: 1 });

    await user.selectOptions(screen.getByRole("combobox", { name: "Rows" }), "50");
    expect(update).toHaveBeenLastCalledWith({ pageSize: 50, page: 1 });
    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(update).toHaveBeenLastCalledWith({ page: 1 });
  });

  it("selects the visible page and exposes recoverable errors", async () => {
    const user = userEvent.setup();
    const selection = vi.fn();
    const retry = vi.fn();
    const props = {
      caption: "Projects",
      columns,
      state,
      update: () => {},
      isLoading: false,
      getRowId: (row: Row) => row.id,
    };
    const { rerender } = render(
      <DataTable
        {...props}
        data={{
          count: 2,
          page: 1,
          page_size: 25,
          total_pages: 1,
          results: [
            { id: "1", name: "Alpha" },
            { id: "2", name: "Beta" },
          ],
        }}
        selection={{}}
        onSelectionChange={selection}
        rowName={(row) => row.name}
      />,
    );

    await user.click(screen.getByRole("checkbox", { name: "Select all rows on this page" }));
    expect(selection).toHaveBeenCalledWith({ "1": true, "2": true });

    rerender(<DataTable {...props} error={new Error("Projects could not be loaded")} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Projects could not be loaded");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
