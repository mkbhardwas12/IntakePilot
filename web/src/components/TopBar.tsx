import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { getHealth } from "../api";
import { currentTheme, setTheme } from "../theme";
import type { Theme } from "../theme";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; provider: string; store: string }
  | { kind: "down" };

export function TopBar() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });
  const [theme, setThemeState] = useState<Theme>(() => currentTheme());

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((h) => {
        if (!cancelled) setHealth({ kind: "ok", provider: h.provider, store: h.store });
      })
      .catch(() => {
        if (!cancelled) setHealth({ kind: "down" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  };

  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="logo-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="22" height="22">
            <defs>
              <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#0d9488" />
                <stop offset="1" stopColor="#22d3ee" />
              </linearGradient>
            </defs>
            <rect width="32" height="32" rx="8" fill="url(#logo-g)" />
            <path
              d="M10 22 L16 9 L22 22 M12.5 17.5 h7"
              stroke="#06282c"
              strokeWidth="2.4"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <span className="wordmark">IntakePilot</span>
        <nav className="topnav">
          <NavLink to="/loop" end className={({ isActive }) => (isActive ? "navlink active" : "navlink")}>
            Intake
          </NavLink>
          <NavLink to="/metrics" className={({ isActive }) => (isActive ? "navlink active" : "navlink")}>
            Metrics
          </NavLink>
        </nav>
      </div>
      <div className="topbar-right">
        <span
          className={
            health.kind === "ok" ? "health-dot ok" : health.kind === "down" ? "health-dot down" : "health-dot"
          }
        />
        <span className="health-label">
          {health.kind === "ok" ? health.provider : health.kind === "down" ? "offline" : "connecting…"}
        </span>
        <button
          className="theme-toggle"
          onClick={toggleTheme}
          title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        >
          {theme === "dark" ? (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <circle cx="8" cy="8" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.4" />
              <g stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
                <path d="M8 1.2v1.8M8 13v1.8M1.2 8h1.8M13 8h1.8M3.2 3.2l1.3 1.3M11.5 11.5l1.3 1.3M12.8 3.2l-1.3 1.3M4.5 11.5l-1.3 1.3" />
              </g>
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path
                d="M13.5 9.7A5.6 5.6 0 0 1 6.3 2.5a5.6 5.6 0 1 0 7.2 7.2Z"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </button>
      </div>
    </header>
  );
}
