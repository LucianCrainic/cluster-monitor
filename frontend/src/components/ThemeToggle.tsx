import { useEffect, useState } from "react";

import {
  THEME_MEDIA_QUERY,
  applyTheme,
  readStoredTheme,
  readSystemTheme,
  storeTheme,
  type Theme,
} from "../theme";

export function ThemeToggle() {
  const [preference, setPreference] = useState<Theme | null>(readStoredTheme);
  const [systemTheme, setSystemTheme] = useState<Theme>(readSystemTheme);
  const theme = preference ?? systemTheme;
  const isDark = theme === "dark";
  const nextTheme = isDark ? "light" : "dark";

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (preference !== null) {
      return;
    }

    const mediaQuery = window.matchMedia?.(THEME_MEDIA_QUERY);
    if (!mediaQuery) {
      return;
    }

    const handleChange = (event: MediaQueryListEvent) => {
      setSystemTheme(event.matches ? "dark" : "light");
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [preference]);

  const toggleTheme = () => {
    setPreference(nextTheme);
    storeTheme(nextTheme);
    applyTheme(nextTheme);
  };

  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${nextTheme} theme`}
      title={`Switch to ${nextTheme} theme`}
    >
      <span className="theme-toggle__icon" aria-hidden="true">
        {isDark ? "☾" : "☀"}
      </span>
      <span className="theme-toggle__text">{isDark ? "Dark" : "Light"}</span>
    </button>
  );
}
