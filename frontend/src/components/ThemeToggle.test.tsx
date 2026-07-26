import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_MEDIA_QUERY, THEME_STORAGE_KEY } from "../theme";
import { ThemeToggle } from "./ThemeToggle";

function installSystemTheme(initiallyDark: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  let matches = initiallyDark;
  const mediaQuery = {
    get matches() {
      return matches;
    },
    media: THEME_MEDIA_QUERY,
    onchange: null,
    addEventListener: vi.fn(
      (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.add(listener);
      },
    ),
    removeEventListener: vi.fn(
      (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.delete(listener);
      },
    ),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList;
  vi.stubGlobal("matchMedia", vi.fn(() => mediaQuery));

  return {
    setDark(nextMatches: boolean) {
      matches = nextMatches;
      act(() => {
        for (const listener of listeners) {
          listener({ matches } as MediaQueryListEvent);
        }
      });
    },
  };
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    vi.unstubAllGlobals();
  });

  it("follows the system theme until the user chooses an override", () => {
    const systemTheme = installSystemTheme(true);
    render(<ThemeToggle />);

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(
      screen.getByRole("button", { name: "Switch to light theme" }),
    ).toHaveTextContent("Dark");

    systemTheme.setDark(false);

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(
      screen.getByRole("button", { name: "Switch to dark theme" }),
    ).toHaveTextContent("Light");
  });

  it("persists an explicit preference and restores it", async () => {
    const systemTheme = installSystemTheme(false);
    const user = userEvent.setup();
    const firstRender = render(<ThemeToggle />);

    await user.click(
      screen.getByRole("button", { name: "Switch to dark theme" }),
    );

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    systemTheme.setDark(false);
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    firstRender.unmount();
    document.documentElement.removeAttribute("data-theme");
    render(<ThemeToggle />);

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(
      screen.getByRole("button", { name: "Switch to light theme" }),
    ).toBeInTheDocument();
  });
});
