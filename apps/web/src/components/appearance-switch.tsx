"use client";

export function AppearanceSwitch() {
  function toggle() {
    const root = document.documentElement;
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
  }
  return (
    <button
      className="appearance-switch"
      data-ui
      type="button"
      onClick={toggle}
      aria-label="Toggle light and dark appearance"
    >
      Appearance
    </button>
  );
}
