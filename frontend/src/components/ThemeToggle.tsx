import { MoonIcon, SunIcon } from "@heroicons/react/24/outline";
import { useEffect, useState } from "react";
import { usePrefs } from "@/store/prefs";

const DARK_SCHEME = "(prefers-color-scheme: dark)";

function systemPrefersDark() {
  return typeof window !== "undefined" && window.matchMedia(DARK_SCHEME).matches;
}

export function ThemeToggle() {
  const theme = usePrefs((state) => state.theme);
  const setTheme = usePrefs((state) => state.setTheme);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    const preference = window.matchMedia(DARK_SCHEME);
    const update = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    setSystemDark(preference.matches);
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);

  const dark = theme === "dark" || (theme === "system" && systemDark);
  const nextTheme = dark ? "light" : "dark";
  const label = `Switch to ${nextTheme} theme`;

  return (
    <button
      id="tour-theme-toggle"
      type="button"
      className="btn btn-square btn-ghost btn-sm"
      aria-label={label}
      title={label}
      onClick={() => setTheme(nextTheme)}
    >
      <span className="theme-toggle-icons" data-dark={dark} aria-hidden="true">
        <MoonIcon className="theme-toggle-icon theme-toggle-icon-moon" />
        <SunIcon className="theme-toggle-icon theme-toggle-icon-sun" />
      </span>
    </button>
  );
}
