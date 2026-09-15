import { Settings } from "../settings";

// Static rendering keeps the local API contract available without client-side data loading.
export const metadata = {
  title: "API contract | Signal Ledger",
  description: "Local Stock Probability API contract",
};

export default function ApiDocsPage() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to API contract</a>
      <header className="masthead api-masthead">
        <div className="masthead-primary">
          <a className="brand-lockup" href="/" aria-label="Signal Ledger dashboard">
            <span className="ledger-mark" aria-hidden="true"><i /><i /><i /></span>
            <span><span className="eyebrow">Precision Research Terminal / API v1</span><h1>Signal Ledger API</h1></span>
          </a>
          <div className="header-controls">
            <a className="text-link" href="/">Return to dashboard</a>
            <Settings />
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <section className="hero api-hero" aria-labelledby="contract-heading">
          <div className="hero-copy">
            <p className="panel-kicker">Local application boundary / OpenAPI 3.1</p>
            <h2 id="contract-heading">API Contract</h2>
            <p className="section-summary">Inspect the request, response, and error schemas used by the research terminal. By default, the service accepts loopback requests only. The browser stays behind its <strong>/api/v1</strong> boundary; direct storage details and access are not exposed, and it never calls the market-data provider directly.</p>
          </div>
          <aside className="search-panel api-actions" aria-labelledby="canonical-heading">
            <p className="panel-kicker">Machine-readable source</p>
            <h3 id="canonical-heading">Canonical OpenAPI specification</h3>
            <p>Use the live contract served by this local instance for complete paths, parameters, and schemas.</p>
            <p><a className="primary" href="/api/v1/openapi.json">Open canonical OpenAPI JSON <span aria-hidden="true">↗</span></a></p>
            <p className="section-summary">No third-party documentation code or remote assets are loaded.</p>
          </aside>
        </section>

        <section className="api-contract-grid" aria-labelledby="endpoint-groups-heading">
          <div>
            <p className="panel-kicker">Quick orientation</p>
            <h2 id="endpoint-groups-heading">Core endpoint groups</h2>
            <p className="section-summary">A compact map of the local surface, not a substitute for the canonical specification.</p>
          </div>
          <ul className="api-endpoint-list">
            <li><h3>Service state</h3><p><code>GET /api/v1/health</code><br /><code>GET /api/v1/readiness</code></p></li>
            <li><h3>Research</h3><p><code>GET /api/v1/instruments</code><br /><code>GET /api/v1/news</code><br /><code>POST /api/v1/forecasts</code></p></li>
            <li><h3>Recorded ledger</h3><p><code>GET /api/v1/history</code><br /><code>GET /api/v1/saved-forecasts/{"{event_id}"}</code></p></li>
            <li><h3>Local operations</h3><p><code>POST /api/v1/operations/backups</code><br /><code>POST /api/v1/operations/restores</code></p></li>
          </ul>
        </section>
      </main>
    </>
  );
}
