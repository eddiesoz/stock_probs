import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

test("theme controls added by a client route sync when Settings opens and changes", async () => {
  const source = await readFile(new URL("../../src/stock_probs/static/theme.js", import.meta.url), "utf8");
  const listeners = new Map();
  const windowListeners = new Map();
  const radios = [];
  const storage = new Map([["stock-probs.theme", "dark"]]);
  const media = {
    matches: false,
    addEventListener(type, listener) {
      listeners.set(`media:${type}`, listener);
    },
  };
  const document = {
    readyState: "complete",
    documentElement: { dataset: {} },
    querySelectorAll(selector) {
      assert.equal(selector, "[name=theme]");
      return radios;
    },
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
  };
  const context = {
    document,
    window: { addEventListener(type, listener) { windowListeners.set(type, listener); } },
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
    matchMedia: () => media,
  };
  vm.runInNewContext(source, context);
  assert.equal(document.documentElement.dataset.theme, "dark");

  const radio = (value) => {
    const element = { value, checked: false };
    element.closest = (selector) => selector === "[name=theme]" ? element : null;
    return element;
  };
  const light = radio("light");
  const dark = radio("dark");
  const system = radio("system");
  radios.push(light, dark, system);

  listeners.get("toggle")({ target: { id: "settings-menu" }, newState: "open" });
  assert.equal(light.checked, false);
  assert.equal(dark.checked, true);
  assert.equal(system.checked, false);

  light.checked = true;
  listeners.get("change")({ target: light });
  assert.equal(document.documentElement.dataset.theme, "light");
  assert.equal(storage.get("stock-probs.theme"), "light");
  assert.equal(light.checked, true);
  assert.equal(dark.checked, false);
  assert.equal(system.checked, false);

  windowListeners.get("signal-ledger:assistant-theme")({ detail: { theme: "system" } });
  assert.equal(storage.has("stock-probs.theme"), false);
  assert.equal(document.documentElement.dataset.theme, "light");
  windowListeners.get("signal-ledger:assistant-theme")({ detail: { theme: "dark", private_value: "ignored" } });
  assert.equal(document.documentElement.dataset.theme, "light");
});
