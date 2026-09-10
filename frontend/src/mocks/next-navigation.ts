// Vite compatibility shim required by nextstepjs. Routing during tours uses its
// React Router adapter; these Next.js exports are never used by the application.
export const useRouter = () => ({
  push: () => {},
  replace: () => {},
  prefetch: () => {},
  back: () => {},
  forward: () => {},
  refresh: () => {},
});

export const usePathname = () => "";
export const useSearchParams = () => new URLSearchParams();
export const useParams = () => ({});
