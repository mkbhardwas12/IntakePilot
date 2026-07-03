export type Theme = "dark" | "light";

const STORAGE_KEY = "intakepilot-theme";

export function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function storedTheme(): Theme | null {
  const v = localStorage.getItem(STORAGE_KEY);
  return v === "dark" || v === "light" ? v : null;
}

export function currentTheme(): Theme {
  return storedTheme() ?? systemTheme();
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function setTheme(theme: Theme): void {
  localStorage.setItem(STORAGE_KEY, theme);
  applyTheme(theme);
}

/** Follow OS changes while the user hasn't made an explicit choice. */
export function watchSystemTheme(onChange?: (t: Theme) => void): () => void {
  const mq = window.matchMedia("(prefers-color-scheme: light)");
  const listener = () => {
    if (storedTheme() === null) {
      applyTheme(systemTheme());
      onChange?.(systemTheme());
    }
  };
  mq.addEventListener("change", listener);
  return () => mq.removeEventListener("change", listener);
}

/** Apply the effective theme at startup and track OS preference changes.
    (index.html also sets data-theme pre-paint to avoid a flash.) */
export function initTheme(): void {
  applyTheme(currentTheme());
  watchSystemTheme();
}
