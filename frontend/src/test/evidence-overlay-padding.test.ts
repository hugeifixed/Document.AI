import { evidenceOverlayPadding, polygonBounds } from "@/components/review/evidence";

function bounds(left: number, top: number, right: number, bottom: number) {
  return polygonBounds([left, top, right, top, right, bottom, left, bottom])!;
}

it("keeps full breathing room around isolated evidence", () => {
  const isolated = bounds(0.1, 0.1, 0.3, 0.2);
  expect(evidenceOverlayPadding(isolated, [isolated])).toEqual({
    top: "4px",
    right: "4px",
    bottom: "4px",
    left: "4px",
  });
});

it("reduces padding on facing edges of nearby evidence", () => {
  const upper = bounds(0.1, 0.1, 0.3, 0.2);
  const lower = bounds(0.1, 0.205, 0.3, 0.3);
  const upperPadding = evidenceOverlayPadding(upper, [upper, lower]);
  const lowerPadding = evidenceOverlayPadding(lower, [upper, lower]);

  expect(upperPadding.bottom).toContain("min(4px");
  expect(lowerPadding.top).toContain("min(4px");
  expect(upperPadding.top).toBe("4px");
  expect(lowerPadding.bottom).toBe("4px");
});

it("does not add padding between provider boxes that already overlap", () => {
  const upper = bounds(0.1, 0.1, 0.3, 0.21);
  const lower = bounds(0.1, 0.2, 0.3, 0.3);

  expect(evidenceOverlayPadding(upper, [upper, lower]).bottom).toBe("0px");
  expect(evidenceOverlayPadding(lower, [upper, lower]).top).toBe("0px");
});
