import { ApiError, tableParams } from "@/api/client";

describe("api client", () => {
  it("builds table params with ordering and search", () => {
    expect(tableParams({ page: 2, pageSize: 25, sort: "created", desc: true, q: "w2", filters: { status: "failed" } }))
      .toEqual({ page: 2, page_size: 25, status: "failed", ordering: "-created", search: "w2" });
  });
  it("normalizes error envelopes", () => {
    const e = new ApiError(422, { success: false, message: "Validation failed.", errors: { name: ["required"] }, error_code: "VALIDATION_ERROR", trace_id: "abc" });
    expect(e.code).toBe("VALIDATION_ERROR"); expect(e.traceId).toBe("abc"); expect(e.errors.name).toEqual(["required"]);
  });
});
