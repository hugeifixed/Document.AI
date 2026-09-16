/* Same-origin API requests only: never forward credentials to a selectable external server. */
(() => {
  const config = JSON.parse(document.getElementById("scalar-config").textContent);
  const csrf = JSON.parse(document.getElementById("csrf-config").textContent);
  const navigation = document.querySelector(".docs-nav");
  // Scalar subtracts this supported offset from its sidebar height and anchor positions.
  // Measure before mounting, then track wrapped links, zoom and font loading.
  const updateHeaderHeight = () => {
    document.documentElement.style.setProperty(
      "--scalar-custom-header-height", `${navigation.getBoundingClientRect().height}px`,
    );
  };
  updateHeaderHeight();
  new ResizeObserver(updateHeaderHeight).observe(navigation);
  config.customFetch = async (input, init) => {
    const outgoing = new Request(input instanceof Request ? input : new URL(input, location.href), init);
    if (new URL(outgoing.url).origin !== location.origin) {
      throw new Error("Use the same-origin DocAI API. External request destinations are disabled.");
    }
    const headers = new Headers(outgoing.headers);
    if (!["GET", "HEAD", "OPTIONS"].includes(outgoing.method.toUpperCase())) {
      // Login rotates Django's CSRF secret. Prefer the current cookie over the page's
      // initial token; the masked token also supports HttpOnly CSRF cookies on page load.
      const cookie = document.cookie.split(";").map((value) => value.trim())
        .find((value) => value.startsWith(`${csrf.cookie}=`));
      headers.set(csrf.header, cookie ? decodeURIComponent(cookie.slice(csrf.cookie.length + 1)) : csrf.token);
    }
    return fetch(new Request(outgoing, { headers, credentials: "same-origin", mode: "same-origin", redirect: "error" }));
  };
  // "api-reference" is reserved for Scalar's automatic HTML initializer. Using it here
  // mounts a second instance with vendor defaults before our configuration is applied.
  Scalar.createApiReference("#scalar-reference", config);
})();
