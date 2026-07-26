export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "cluster-monitor.theme";
export const THEME_MEDIA_QUERY = "(prefers-color-scheme: dark)";

export function readStoredTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function readSystemTheme(): Theme {
  return window.matchMedia?.(THEME_MEDIA_QUERY).matches ? "dark" : "light";
}

export function storeTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The in-memory preference still works when storage is unavailable.
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function initializeTheme(): Theme {
  const theme = readStoredTheme() ?? readSystemTheme();
  applyTheme(theme);
  return theme;
}
