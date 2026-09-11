import {
  acknowledgeProductTour,
  hasAcknowledgedProductTour,
  productTourStorageKey,
} from "@/components/productTourStorage";

describe("product tour acknowledgement", () => {
  beforeEach(() => localStorage.clear());

  it("persists completion or dismissal separately for each user", () => {
    expect(hasAcknowledgedProductTour("first.user")).toBe(false);
    acknowledgeProductTour("first.user");

    expect(hasAcknowledgedProductTour("first.user")).toBe(true);
    expect(hasAcknowledgedProductTour("second.user")).toBe(false);
    expect(productTourStorageKey("first.user")).not.toBe(productTourStorageKey("second.user"));
  });
});
