import { polygonBounds } from "@/components/review/geometry";

describe("review overlay geometry", () => {
  it("converts a normalized polygon to percentage bounds", () => {
    expect(polygonBounds([0.25, 0.25, 0.5, 0.25, 0.5, 0.75, 0.25, 0.75])).toEqual({
      left: "25%",
      top: "25%",
      width: "25%",
      height: "50%",
    });
  });

  it("ignores incomplete polygons", () => {
    expect(polygonBounds([0.1, 0.2])).toBeNull();
  });
});
