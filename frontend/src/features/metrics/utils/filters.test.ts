import { readFilters, updateFilters, validateDates } from "./filters";
it("validates exact inclusive dates and rejects invalid/future/reversed/oversized ranges", () => {
  expect(validateDates("2026-06-04", "2026-09-01", "2026-09-01")).toBeUndefined();
  expect(validateDates("2026-06-03", "2026-09-01", "2026-09-01")).toMatch(/90/);
  expect(validateDates("2026-02-30", "2026-03-02", "2026-09-01")).toMatch(/valid/);
  expect(validateDates("2026-09-02", "2026-09-01", "2026-09-01")).toMatch(/before/);
  expect(validateDates("2026-09-01", "2026-09-02", "2026-09-01")).toMatch(/future/);
});
it("keeps shared workspace/dates but isolates each endpoint's filters", () => {
  const filters = readFilters(
    new URLSearchParams(
      "range=7d&status=failed&document_type=invoice&provider=azure&deployment=extract&stage=extraction",
    ),
    { project: "p", dataset: "d" },
  );
  expect(filters.processing).toEqual({
    project: "p",
    dataset: "d",
    range: "7d",
    status: "failed",
    document_type: "invoice",
  });
  expect(filters.usage).toEqual({
    project: "p",
    dataset: "d",
    range: "7d",
    provider: "azure",
    deployment: "extract",
    stage: "extraction",
  });
  expect(readFilters(new URLSearchParams("range=bogus"), {}).error).toMatch(/date range/);
  expect(readFilters(new URLSearchParams("status=running"), {}).error).toMatch(/job status/);
});
it("updates URL filters without discarding another section's filter", () => {
  expect(
    updateFilters(new URLSearchParams("provider=azure&status=failed"), { status: "", range: "today" }).toString(),
  ).toBe("provider=azure&range=today");
});
