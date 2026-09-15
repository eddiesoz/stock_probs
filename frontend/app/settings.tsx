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
        <svg className="settings-trigger-icon" aria-hidden="true" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v3m0 14v3M2 12h3m14 0h3M4.9 4.9 7 7m10 10 2.1 2.1m0-14.2L17 7M7 17l-2.1 2.1" />
        </svg>
        Settings
      </button>
      <div
        id="settings-menu"
        className="settings-menu"
        popover=""
        role="dialog"
        aria-labelledby="settings-heading"
        onFocus={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            event.currentTarget.previousElementSibling?.scrollIntoView({
              behavior: "instant",
              block: "nearest",
            });
          }
        }}
      >
        <div className="settings-menu-header">
          <h2 id="settings-heading">Settings</h2>
          <button
            className="settings-close secondary"
            type="button"
            popoverTarget="settings-menu"
            popoverTargetAction="hide"
            aria-label="Close settings"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <fieldset className="theme-control" aria-describedby="theme-description">
          <legend>Theme</legend>
          <p id="theme-description" className="theme-description">
            {/* Stable line boxes keep text contrast unambiguous over content beneath the nonmodal popover. */}
            <span>Choose your appearance.</span>{" "}<span>Changes apply immediately.</span>
          </p>
          <div className="theme-options">
            <label className="theme-option">
              <span className="theme-option-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4m0-14.2-1.4 1.4M6.3 17.7l-1.4 1.4" /></svg>
              </span>
              <span className="theme-option-copy"><span className="theme-option-title">Light</span><span>Bright background</span></span>
              <input type="radio" name="theme" value="light" aria-label="Light" />
            </label>
            <label className="theme-option">
              <span className="theme-option-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M20 15.4A8.5 8.5 0 0 1 8.6 4a8.5 8.5 0 1 0 11.4 11.4Z" /></svg>
              </span>
              <span className="theme-option-copy"><span className="theme-option-title">Dark</span><span>Dim background</span></span>
              <input type="radio" name="theme" value="dark" aria-label="Dark" />
            </label>
            <label className="theme-option">
              <span className="theme-option-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8m-4-4v4" /></svg>
              </span>
              <span className="theme-option-copy"><span className="theme-option-title">System</span><span>Follow your device appearance</span></span>
              <input type="radio" name="theme" value="system" aria-label="System" />
            </label>
          </div>
        </fieldset>
      </div>
    </>
  );
}
