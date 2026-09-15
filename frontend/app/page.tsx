import Script from "next/script";

import { Settings } from "./settings";

// Existing app.js owns interaction while this route supplies stable server-rendered hooks.
export const metadata = {
  title: "Signal Ledger | Stock Probability",
  description: "Local, auditable stock and ETF probability forecasts",
};

export default function DashboardPage() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to forecasts</a>
      <header className="masthead">
        <div className="masthead-primary">
          <a className="brand-lockup" href="#main" aria-label="Signal Ledger home">
            <span><span className="eyebrow">Local research terminal / API v1</span><h1>Signal Ledger</h1></span>
          </a>
          <div className="header-controls">
            <nav className="section-nav" aria-label="Dashboard sections">
              <a href="#forecast-heading"><span>01</span> Forecast</a>
              <a href="#result-heading"><span>02</span> Analysis</a>
              <a href="#history-heading"><span>03</span> Ledger</a>
            </nav>
            <Settings />
          </div>
        </div>
        <div className="system-state" role="status" aria-live="polite" aria-label="System status">
          <span className="status-dot" aria-hidden="true" />
          <span id="system-label">Checking local service</span>
        </div>
      </header>

      <main id="main" tabIndex={-1}>
        <section className="hero" aria-labelledby="forecast-heading">
          <div className="hero-copy workspace-intro">
            <p className="section-number panel-kicker">01 / Forecast workspace</p>
            <h2 id="forecast-heading" className="workspace-title">Next-close probability forecast</h2>
            <p className="workspace-summary">Compare close-to-close and latest-completed-five-minute-bar horizons with explicit probabilities, ranges, and model evidence.</p>
            <p className="desk-meta">Local FastAPI /api/v1 · Two horizons · Immutable audit ledger</p>
          </div>
          <form id="forecast-form" className="search-panel" noValidate>
            <p className="panel-kicker">Instrument composer</p>
            <div className="field symbol-field">
              <div className="field-heading">
                <label htmlFor="symbol">Company name or Yahoo Finance symbol</label>
                <span className="field-index" aria-hidden="true">QUERY / 01</span>
              </div>
              <input id="symbol" name="symbol" type="text" defaultValue="ACDC" maxLength={80} autoComplete="off" spellCheck={false} role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="instrument-options" aria-describedby="symbol-help lookup-status identity-confirmation symbol-error" required />
              <p id="symbol-help" className="hint">Type a company name to choose its identity, or enter a symbol directly.</p>
              <p id="lookup-status" className="hint lookup-status" role="status" aria-live="polite" />
              <ul id="instrument-options" className="instrument-options" role="listbox" aria-label="Matching instruments" hidden />
              <div id="identity-confirmation" className="identity-confirmation" aria-live="polite" hidden />
              <p id="symbol-error" className="field-error" aria-live="polite" />
            </div>
            <fieldset className="asset-field">
              <legend>Asset type</legend>
              <label><input type="radio" name="asset_type" value="stock" defaultChecked /> Stock</label>
              <label><input type="radio" name="asset_type" value="etf" /> ETF</label>
            </fieldset>
            <button id="forecast-submit" className="primary" type="submit"><span>Run forecast</span></button>
          </form>
        </section>

        <div id="announcement" className="sr-only" aria-live="polite" aria-atomic="true" />
        <section id="result-section" className="results" aria-labelledby="result-heading" tabIndex={-1}>
          <div className="section-head">
            <div>
              <p className="section-number panel-kicker">02 / Horizon analysis</p>
              <h2 id="result-heading">Forecast comparison</h2>
              <p className="section-summary">Two completed origins, one next-close target, with probabilities and intervals shown together.</p>
            </div>
            <span id="quality-badge" className="badge neutral">Awaiting input</span>
          </div>
          <div id="result-content" className="empty-state" aria-busy="false">
            <span className="empty-orbit" aria-hidden="true"><i /></span>
            <h3>No forecast loaded</h3>
            <p>Choose an instrument to calculate two traceable probability distributions.</p>
          </div>
        </section>

        <section id="fresh-analysis-section" className="fresh-analysis" aria-labelledby="fresh-analysis-heading" tabIndex={-1} hidden>
          <div className="section-head">
            <div>
              <p className="section-number panel-kicker">02b / Separate analysis</p>
              <h2 id="fresh-analysis-heading">Fresh historical-cutoff analysis</h2>
            </div>
            <span className="badge fresh">New calculation</span>
          </div>
          <p className="fresh-warning"><strong>Not the saved forecast.</strong> This separate calculation uses the selected event’s historical cutoff and records its own as-of time and provenance. The immutable recorded result above remains unchanged.</p>
          <div id="fresh-analysis-content" aria-live="polite" />
        </section>

        <section className="ledger" aria-labelledby="history-heading">
          <div className="section-head">
            <div>
              <p className="section-number panel-kicker">03 / Permanent record</p>
              <h2 id="history-heading">Search ledger</h2>
            </div>
            <fieldset className="export-controls">
              <legend className="sr-only">Download filtered history</legend>
              <a id="export-csv" className="text-link" href="/api/v1/history-export.csv" download>Download CSV</a>
              <a id="export-json" className="text-link" href="/api/v1/history-export.json" download>Download JSON</a>
            </fieldset>
          </div>
          <p className="ledger-intro section-summary">Search every submitted request by instrument, status, model, horizon, or date. Saved results are immutable and never expire automatically; fresh historical-cutoff analysis remains a separate calculation.</p>
          <form id="history-form" className="history-filters" role="search">
            <div className="field">
              <label htmlFor="history-query">Find symbol or company</label>
              <input id="history-query" name="q" type="search" maxLength={30} placeholder="ACDC" />
            </div>
            <div className="field">
              <label htmlFor="history-status">Status</label>
              <select id="history-status" name="status" defaultValue="">
                <option value="">All states</option>
                <option value="successful">Successful</option>
                <option value="repeated">Repeated</option>
                <option value="failed">Failed</option>
              </select>
            </div>
            <details className="advanced-filters">
              <summary>More filters</summary>
              <div className="advanced-filter-grid">
                <div className="field">
                  <label htmlFor="history-asset">Asset type</label>
                  <select id="history-asset" name="asset_type" defaultValue="">
                    <option value="">All types</option>
                    <option value="stock">Stock</option>
                    <option value="etf">ETF</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="history-analysis">Analysis type</label>
                  <select id="history-analysis" name="analysis_kind" defaultValue="">
                    <option value="">All analyses</option>
                    <option value="submitted_forecast">Submitted forecasts</option>
                    <option value="fresh_historical_reconstruction">Fresh cutoff analyses</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="history-from">Submitted from</label>
                  <input id="history-from" name="submitted_from" type="date" />
                </div>
                <div className="field">
                  <label htmlFor="history-to">Submitted through</label>
                  <input id="history-to" name="submitted_to" type="date" />
                </div>
                <div className="field">
                  <label htmlFor="history-model">Model name or version</label>
                  <input id="history-model" name="model" type="search" maxLength={120} placeholder="empirical" />
                </div>
                <div className="field">
                  <label htmlFor="history-horizon">Forecast horizon</label>
                  <select id="history-horizon" name="horizon" defaultValue="">
                    <option value="">Both horizons</option>
                    <option value="close_to_close">Close to next close</option>
                    <option value="completed_5m_to_close">Completed 5m to close</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="history-sort">Sort ledger</label>
                  <select id="history-sort" name="sort" defaultValue="event_id:desc">
                    <option value="event_id:desc">Newest request first</option>
                    <option value="event_id:asc">Oldest request first</option>
                    <option value="symbol:asc">Symbol A–Z</option>
                    <option value="company:asc">Company A–Z</option>
                    <option value="status:asc">Status A–Z</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="history-page-size">Rows per page</label>
                  <select id="history-page-size" name="page_size" defaultValue="10">
                    <option value="10">10</option>
                    <option value="20">20</option>
                    <option value="50">50</option>
                  </select>
                </div>
              </div>
            </details>
            <button className="secondary" type="submit">Filter ledger</button>
          </form>
          <div id="history-content" className="history-content" aria-live="polite">
            <p>Loading local history…</p>
          </div>
          <nav className="pagination" aria-label="History pages">
            <button id="history-previous" className="secondary" type="button" disabled>Previous</button>
            <span id="history-page" role="status">Page 1</span>
            <button id="history-next" className="secondary" type="button" disabled>Next</button>
          </nav>
        </section>
      </main>

      <footer className="terminal-footer">
        <p>Research output, not investment advice. Provider, model, version, and limitations are shown with every result.</p>
      </footer>
      <Script src="/assets/app.js" strategy="afterInteractive" />
    </>
  );
}
