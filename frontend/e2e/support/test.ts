import { expect, test as base, type Route } from "@playwright/test";

interface ApiGuard {
  reject(route: Route): Promise<void>;
}

export const test = base.extend<{ apiGuard: ApiGuard }>({
  apiGuard: async ({}, use) => {
    const unexpectedRequests: string[] = [];

    await use({
      async reject(route) {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        unexpectedRequests.push(`${request.method()} ${path}`);
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            message: `No browser-test handler for ${path}`,
            errors: [],
            error_code: "BROWSER_TEST_UNHANDLED_REQUEST",
            trace_id: "browser-test",
          }),
        });
      },
    });

    expect(unexpectedRequests, "Every API request must have an explicit browser-test handler").toEqual([]);
  },
});

export { expect };
