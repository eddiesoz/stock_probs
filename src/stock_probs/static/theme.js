/* Apply theme before CSS to prevent first-paint flash. */
"use strict";
(() => {
const key = "stock-probs.theme";
const media = matchMedia("(prefers-color-scheme: dark)");
let choice = null;
try {
  const saved = localStorage.getItem(key);
  if (saved === "light" || saved === "dark") choice = saved;
  else if (saved !== null) localStorage.removeItem(key);
} catch (_) {}
const apply = () => { document.documentElement.dataset.theme = choice || (media.matches ? "dark" : "light"); };
apply();
const bind = () => document.querySelectorAll('.theme-control select[name="theme"]').forEach((control) => {
  control.value = choice || "system";
  control.addEventListener("change", () => {
    choice = control.value === "system" ? null : control.value;
    try { choice ? localStorage.setItem(key, choice) : localStorage.removeItem(key); } catch (_) {}
    apply();
  });
});
document.addEventListener("DOMContentLoaded", bind, { once: true });
media.addEventListener("change", () => { if (!choice) apply(); });
})();
