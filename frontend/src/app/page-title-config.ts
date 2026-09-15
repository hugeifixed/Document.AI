/** Shared by React and Vite's HTML fallback transform. Values are public build configuration. */
export function createPageTitleConfig(env: { VITE_APPLICATION_NAME?: string; VITE_DEPLOYMENT_ENV?: string } = {}) {
  return {
    applicationName: env.VITE_APPLICATION_NAME?.trim() || "Document AI",
    environment: env.VITE_DEPLOYMENT_ENV?.trim().toUpperCase() || "DEV",
    separator: " | ",
    fallbackPage: "Workspace",
  };
}

export type PageTitleConfig = ReturnType<typeof createPageTitleConfig>;

export function formatPageTitle(label: string | undefined, config: PageTitleConfig) {
  const prefix = ["PROD", "PRODUCTION"].includes(config.environment) ? "" : `[${config.environment}] `;
  return `${prefix}${label?.trim() || config.fallbackPage}${config.separator}${config.applicationName}`;
}

export function fallbackTitleHtml(config: PageTitleConfig) {
  const escaped = config.applicationName.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return `<title>${escaped}</title>`;
}
