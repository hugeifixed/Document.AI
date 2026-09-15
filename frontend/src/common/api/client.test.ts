import { ApiError, apiFieldError, get, http, tableParams } from "@/common/api/client";

describe("api client", () => {
  it("builds table params with ordering and search", () => {
    expect(
      tableParams({ page: 2, pageSize: 25, sort: "created", desc: true, q: "w2", filters: { status: "failed" } }),
    ).toEqual({ page: 2, page_size: 25, status: "failed", ordering: "-created", search: "w2" });
  });
  it("normalizes error envelopes", () => {
    const errors = [{ field: "name", message: "This field is required.", code: "required" }];
    const e = new ApiError(422, {
      success: false,
      message: "Validation failed.",
      errors,
      error_code: "VALIDATION_ERROR",
      trace_id: "abc",
    });
    expect(e.code).toBe("VALIDATION_ERROR");
    expect(e.traceId).toBe("abc");
    expect(e.errors).toEqual(errors);
    expect(apiFieldError(e, "name")).toBe("This field is required.");
  });
  it("passes abort signals through to Axios", async () => {
    const controller = new AbortController();
    const request = vi.spyOn(http, "get").mockResolvedValue({ data: { data: { ok: true } } });
    await get<{ ok: boolean }>("/example/", { page: 2 }, { signal: controller.signal });
    expect(request).toHaveBeenCalledWith("/example/", { params: { page: 2 }, signal: controller.signal });
    request.mockRestore();
  });
});
