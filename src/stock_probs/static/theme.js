/* Run before CSS so the first styled paint uses the persisted or system theme. */
"use strict";
(() => {
const key = "stock-probs.theme";
const media = matchMedia("(prefers-color-scheme: dark)");
let choice = null;
try {
  const saved = localStorage.getItem(key);
  if (["light", "dark"].includes(saved)) choice = saved;
  else if (saved !== null) localStorage.removeItem(key);
} catch (_) {}
const apply = () => { document.documentElement.dataset.theme = choice || (media.matches ? "dark" : "light"); };
apply();
const bind = () => document.querySelectorAll('.theme-control select[name="theme"]').forEach((control) => {
  control.value = choice || "system";
  control.addEventListener("change", () => {
    choice = control.value === "system" ? null : control.value;
    try {
      if (choice) localStorage.setItem(key, choice);
      else localStorage.removeItem(key);
    } catch (_) {}
    apply();
  });
});
document.addEventListener("DOMContentLoaded", bind, { once: true });
media.addEventListener("change", () => { if (!choice) apply(); });
})();
