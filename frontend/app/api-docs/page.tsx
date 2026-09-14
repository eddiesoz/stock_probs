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
      <header className="masthead masthead-primary">
        <div>
          <p className="eyebrow">Local application boundary / v1</p>
          <h1>Signal Ledger API</h1>
        </div>
        <Settings />
      </header>
      <main id="main" tabIndex={-1}>
        <section className="hero" aria-labelledby="contract-heading">
          <div className="hero-copy">
            <p className="section-number">OpenAPI / 3.1</p>
            <h2 id="contract-heading">A local, inspectable contract.</h2>
            <p>The machine-readable specification defines each success payload and the shared structured error envelope without loading third-party code.</p>
          </div>
          <div className="search-panel">
            <p className="section-number">Canonical specification</p>
            <p><a className="primary" href="/api/v1/openapi.json">Open OpenAPI JSON <span aria-hidden="true">↗</span></a></p>
            <p>Application data remains available only below <strong>/api/v1</strong>.</p>
          </div>
        </section>
      </main>
    </>
  );
}
