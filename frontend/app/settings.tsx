"use client";

// Native popover owns state; revealing its anchor keeps reverse-Tab focus visible after page scroll.
export function Settings() {
  return (
    <>
      <button
        className="settings-trigger secondary"
        type="button"
        popoverTarget="settings-menu"
        onFocus={(event) => event.currentTarget.scrollIntoView({
          behavior: "instant",
          block: "nearest",
        })}
      >
        Settings
      </button>
      <div
        id="settings-menu"
        className="settings-menu"
        popover=""
        role="dialog"
        aria-label="Settings"
        onFocus={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            event.currentTarget.previousElementSibling?.scrollIntoView({
              behavior: "instant",
              block: "nearest",
            });
          }
        }}
      >
        <fieldset className="theme-control">
          <legend>Theme</legend>
          <div className="theme-options">
            <label><input type="radio" name="theme" value="light" /> Light</label>
            <label><input type="radio" name="theme" value="dark" /> Dark</label>
            <label><input type="radio" name="theme" value="system" /> System</label>
          </div>
        </fieldset>
      </div>
    </>
  );
}
