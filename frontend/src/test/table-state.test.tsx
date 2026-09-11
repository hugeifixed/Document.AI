import { act, fireEvent, render, screen } from "@testing-library/react";
import { useDebouncedSearch } from "@/hooks/useTableState";

function Search({ initial, onChange }: { initial?: string; onChange: (value: string) => void }) {
  const [value, setValue] = useDebouncedSearch(initial, onChange, 300);
  return <input aria-label="Search" value={value} onChange={(event) => setValue(event.target.value)} />;
}

describe("useDebouncedSearch", () => {
  afterEach(() => vi.useRealTimers());

  it("cancels pending input when navigation restores another search value", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const { rerender } = render(<Search initial="old" onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "pending" } });
    rerender(<Search initial="restored" onChange={onChange} />);
    act(() => vi.advanceTimersByTime(300));

    expect(screen.getByLabelText("Search")).toHaveValue("restored");
    expect(onChange).not.toHaveBeenCalled();
  });
});
