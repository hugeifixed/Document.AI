import { errorPageTitle } from "./error-page-title";

it.each([
  [{ status: 403 }, "Access Denied"],
  [{ status: 404 }, "Page Not Found"],
  [{ status: 500 }, "Page Error"],
  [new Error("sensitive record"), "Page Error"],
  [null, "Page Error"],
])("classifies errors without exposing their content", (error, expected) => {
  expect(errorPageTitle(error)).toBe(expected);
});
