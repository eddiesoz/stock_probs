// A draft is local form state until the owner explicitly saves a reviewed revision.
"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { researchRequest, type ResearchPage } from "./research-client";
import styles from "./research.module.css";

type ThesisData = { symbol: string; asset_type: "stock" | "etf"; title: string; reasoning: string; risks: string; invalidation: string; status: "watching" | "active" | "archived"; review_date: string | null; reviewed_at?: string; evidence: { kind: "forecast" | "assistant"; reference: string; excerpt?: string }[]; identity?: { display_name: string; exchange: string } };
type ThesisItem = { id: string; revision: number; created_at: string; updated_at: string; data: ThesisData };
type Revision = { revision: number; data: ThesisData; recorded_at: string };
const blank = (): ThesisData => ({ symbol: "", asset_type: "stock", title: "", reasoning: "", risks: "", invalidation: "", status: "watching", review_date: null, evidence: [] });

function lastContentRevisionAt(history: ResearchPage<Revision> | null, revision: number) {
  if (!history) return null;
  const byRevision = new Map(history.items.map(item => [item.revision, item] as const));
  const contentFields: (keyof ThesisData)[] = ["symbol", "asset_type", "title", "reasoning", "risks", "invalidation", "evidence"];
  for (let currentRevision = revision; currentRevision > 1; currentRevision -= 1) {
    const current = byRevision.get(currentRevision);
    const previous = byRevision.get(currentRevision - 1);
    if (!current || !previous) return null;
    if (contentFields.some(field => JSON.stringify(current.data[field]) !== JSON.stringify(previous.data[field]))) {
      return current.recorded_at;
    }
  }
  return null;
}

function timelineDate(value?: string | null) {
  if (!value) return "Unknown";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString() : "Unknown";
}

export function Theses() {
  const [items, setItems] = useState<ThesisItem[]>([]), [selected, setSelected] = useState<ThesisItem | null>(null);
  const [draft, setDraft] = useState<ThesisData | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true), [page, setPage] = useState(1), [hasNext, setHasNext] = useState(false), [reload, setReload] = useState(0);
  const [listOpen, setListOpen] = useState(true);
  const [history, setHistory] = useState<ResearchPage<Revision> | null>(null), [historyPage, setHistoryPage] = useState(1);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [evidenceKind, setEvidenceKind] = useState<"forecast" | "assistant">("forecast"), [reference, setReference] = useState("");
  const [reviewing, setReviewing] = useState(false), [nextReview, setNextReview] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const operationKey = useRef("");
  const focusAfterSave = useRef(false);
  useEffect(() => { if (focusAfterSave.current && !draft && selected) { heading.current?.focus(); focusAfterSave.current = false; } }, [draft, selected]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    researchRequest<ResearchPage<ThesisItem>>(`/api/v1/theses?page=${page}`, { signal: controller.signal }).then(data => {
      if (!Array.isArray(data.items)) throw new Error("The thesis list is malformed.");
      if (!controller.signal.aborted) { setItems(data.items); setHasNext(data.has_next); }
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page, reload]);
  useEffect(() => {
    const messageId = new URLSearchParams(window.location.search).get("assistant_message");
    if (!messageId) return;
    const controller = new AbortController();
    researchRequest<{ reasoning: string; evidence: ThesisData["evidence"]; truncated: boolean }>(`/api/v1/theses/draft?message_id=${encodeURIComponent(messageId)}`, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      operationKey.current = crypto.randomUUID(); setSelected(null); setListOpen(false); setDraft({ ...blank(), reasoning: data.reasoning, evidence: data.evidence });
      window.history.replaceState(null, "", "/research/theses");
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const thesisId = new URLSearchParams(window.location.search).get("thesis_id");
    if (!thesisId) return;
    const controller = new AbortController();
    researchRequest<ThesisItem>(`/api/v1/theses/${encodeURIComponent(thesisId)}`, { signal: controller.signal }).then(item => {
      if (!controller.signal.aborted) { focusAfterSave.current = true; setSelected(item); setListOpen(false); setDraft(null); }
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);
  const localDate = new Date();
  const today = `${localDate.getFullYear()}-${String(localDate.getMonth() + 1).padStart(2, "0")}-${String(localDate.getDate()).padStart(2, "0")}`;
  const change = <K extends keyof ThesisData>(key: K, value: ThesisData[K]) => setDraft(old => old ? { ...old, [key]: value } : old);
  async function save(event: FormEvent) {
    event.preventDefault(); if (!draft || busy) return; setBusy(true); setError("");
    const { identity: ignored, reviewed_at: previousReview, ...body } = draft; void ignored; void previousReview;
    try {
      const item = await researchRequest<ThesisItem>(selected ? `/api/v1/theses/${selected.id}` : "/api/v1/theses", { method: selected ? "PUT" : "POST", body: JSON.stringify({ ...body, ...(selected ? { revision: selected.revision } : { idempotency_key: operationKey.current }) }) });
      focusAfterSave.current = true; setSelected(item); setDraft(null); setHistory(null); setHistoryOpen(false); setReload(value => value + 1); heading.current?.focus();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Your thesis could not be saved."); } finally { setBusy(false); }
  }
  async function recordReview(event: FormEvent) {
    event.preventDefault(); if (!selected || busy) return; setBusy(true); setError("");
    try { const item = await researchRequest<ThesisItem>(`/api/v1/theses/${selected.id}/review`, { method: "POST", body: JSON.stringify({ revision: selected.revision, next_review_date: nextReview || null }) }); focusAfterSave.current = true; setSelected(item); setReviewing(false); setHistory(null); setHistoryOpen(false); setReload(value => value + 1); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The review could not be recorded."); } finally { setBusy(false); }
  }
  async function revisions(nextPage = 1) {
    if (!selected || busy) return; setBusy(true); setError("");
    try {
      const result = await researchRequest<ResearchPage<Revision>>(`/api/v1/theses/${selected.id}/revisions?page=${nextPage}`);
      setHistory(result); setHistoryPage(nextPage); setHistoryOpen(true);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Revision history is unavailable."); } finally { setBusy(false); }
  }
  function askAssistantToDraft(symbol: string) {
    if (!document.querySelector('[aria-label="Open Ledger assistant"]')) {
      setError("The assistant is unavailable. You can write and save your own thesis.");
      return;
    }
    window.dispatchEvent(new CustomEvent("signal-ledger:thesis-draft-request", {
      detail: `Help me draft an investment thesis for ${symbol || "an instrument I will choose"}. Separate reasoning, evidence, risks and what would change my mind. Ask for missing information; do not invent evidence or save anything.`,
    }));
  }
  const revisedAt = selected ? lastContentRevisionAt(history, selected.revision) : null;
  return <main id="main" tabIndex={-1} className={styles.page}>
    <header className={`${styles.head} ${styles.thesesHead}`}>
      <div><p className="panel-kicker">Research / Theses</p><h1>Theses</h1><p>Your research theses.</p></div>
      <div className={styles.headerActions}>
        <details className={styles.exportDisclosure}>
          <summary>Export theses</summary>
          <div className={styles.exportLinks}><a href="/api/v1/theses/export?format=csv">CSV</a><a href="/api/v1/theses/export?format=json">JSON</a></div>
        </details>
        <button className="primary" disabled={busy || loading} onClick={() => { setSelected(null); setListOpen(false); operationKey.current = crypto.randomUUID(); setDraft(blank()); setHistory(null); setHistoryOpen(false); }}>New thesis</button>
      </div>
    </header>
    {error && <div role="alert" className={styles.error}>{error}<div className={styles.actions}><button className="secondary" onClick={() => setReload(value => value + 1)}>Retry loading</button></div></div>}
    {loading && <p role="status">Loading your theses…</p>}
    <div className={styles.split}><aside className={`${styles.card} ${styles.thesisList}`} aria-label="My theses">
      <button type="button" className={styles.thesisListToggle} aria-expanded={listOpen} onClick={() => setListOpen(value => !value)}>{listOpen ? "Hide My theses" : `My theses (${items.length})`}</button>
      <div className={styles.thesisListContent} data-collapsed={!listOpen}>
        <h2>My theses</h2>{!loading && !items.length && !error && <p>No theses yet. Record an idea to start your research history.</p>}<ul className={styles.list}>{items.map(item => <li key={item.id}><button disabled={busy} aria-pressed={selected?.id === item.id} onClick={() => { focusAfterSave.current = true; setSelected(item); setListOpen(false); setDraft(null); setHistory(null); setHistoryOpen(false); setReviewing(false); }}><strong>{item.data.symbol}</strong><small>{item.data.title}</small><small>{item.data.status} · Updated {timelineDate(item.updated_at)}</small></button></li>)}</ul><div className={styles.actions}><button className="secondary" disabled={page === 1 || loading} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {page}</span><button className="secondary" disabled={!hasNext || loading} onClick={() => setPage(value => value + 1)}>Next</button></div>
      </div>
    </aside>
    <section aria-label="Thesis detail">
      {draft ? <article className={styles.card}><h2>{selected ? "Edit thesis" : "New thesis"}</h2><form onSubmit={save} className={styles.form}>
        <label>Instrument symbol<input required maxLength={15} value={draft.symbol} onChange={e => change("symbol", e.target.value.toUpperCase())} /></label><label>Instrument type<select value={draft.asset_type} onChange={e => change("asset_type", e.target.value as "stock" | "etf")}><option value="stock">Stock</option><option value="etf">ETF</option></select></label>
        <label className={styles.wide}>Title<input required maxLength={160} value={draft.title} onChange={e => change("title", e.target.value)} /></label>
        <p className={`${styles.notice} ${styles.wide}`}>Review all draft text and evidence before saving. Assistant text may be incomplete or incorrect.</p><button type="button" className="secondary" onClick={() => askAssistantToDraft(draft.symbol)}>Ask assistant to draft</button><label className={styles.wide}>My thesis<textarea maxLength={6000} value={draft.reasoning} onChange={e => change("reasoning", e.target.value)} /></label><label>Risks<textarea maxLength={4000} value={draft.risks} onChange={e => change("risks", e.target.value)} /></label><label>What would change my mind<textarea maxLength={4000} value={draft.invalidation} onChange={e => change("invalidation", e.target.value)} /></label>
        <label>Status<select value={draft.status} onChange={e => change("status", e.target.value as ThesisData["status"])}><option value="watching">Watching</option><option value="active">Active</option><option value="archived">Archived</option></select></label><label>Review date<input type="date" value={draft.review_date ?? ""} onChange={e => change("review_date", e.target.value || null)} /></label>
        <fieldset className={styles.wide}><legend>Attach a record you reviewed</legend><label>Evidence type<select value={evidenceKind} onChange={e => setEvidenceKind(e.target.value as "forecast" | "assistant")}><option value="forecast">Saved forecast event</option><option value="assistant">Selected assistant message</option></select></label><label>Record ID<input value={reference} onChange={e => setReference(e.target.value)} maxLength={36} /></label><button type="button" className="secondary" disabled={!reference || draft.evidence.length >= 20} onClick={() => { change("evidence", [...draft.evidence, { kind: evidenceKind, reference }]); setReference(""); }}>Attach evidence</button><ul>{draft.evidence.map((item, index) => <li key={`${item.kind}-${item.reference}-${index}`}>{item.kind} · {item.reference}<button type="button" className="secondary" onClick={() => change("evidence", draft.evidence.filter((_, i) => index !== i))}>Remove attachment</button></li>)}</ul></fieldset>
        <div className={`${styles.actions} ${styles.wide}`}><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save reviewed thesis"}</button><button type="button" className="secondary" disabled={busy} onClick={() => setDraft(null)}>Cancel</button></div>
      </form></article> : selected ? <article className={styles.card}><span className={styles.status}>{selected.data.status}</span><p className={styles.muted}>{selected.data.symbol} · {selected.data.identity?.display_name} · {selected.data.identity?.exchange}</p><h2 ref={heading} tabIndex={-1}>{selected.data.title}</h2><div className={styles.grid}><section><h3>My thesis</h3><p>{selected.data.reasoning || "No reasoning recorded."}</p></section><section><h3>Evidence</h3>{selected.data.evidence.length ? <ul>{selected.data.evidence.map((item, i) => <li key={i}>{item.kind === "forecast" ? <a href={`/?event_id=${encodeURIComponent(item.reference)}`}>Saved forecast · Event #{item.reference}</a> : <details><summary>Selected assistant message · {item.reference}</summary><p>{item.excerpt ?? "No excerpt captured; reopen the saved conversation to review this record."}</p></details>}</li>)}</ul> : <p>No evidence attached.</p>}</section><section><h3>Risks</h3><p>{selected.data.risks || "No risks recorded."}</p></section><section><h3>What would change my mind</h3><p>{selected.data.invalidation || "No invalidation conditions recorded."}</p></section></div><div className={styles.notice}>Review date: {selected.data.review_date ?? "Not set"}{selected.data.review_date && selected.data.review_date <= today && selected.data.status !== "archived" ? " · Review due" : ""}</div><div className={styles.timeline} role="group" aria-label="Thesis timeline">
        <div><span>Created</span><time dateTime={selected.created_at}>{timelineDate(selected.created_at)}</time></div>
        <div><span>Reviewed</span>{selected.data.reviewed_at ? <time dateTime={selected.data.reviewed_at}>{timelineDate(selected.data.reviewed_at)}</time> : <span>Unknown</span>}</div>
        <div><span>Revised</span>{revisedAt ? <time dateTime={revisedAt}>{timelineDate(revisedAt)}</time> : <span>Unknown</span>}</div>
      </div><a href={`/research/theses?thesis_id=${encodeURIComponent(selected.id)}`}>Reopen this thesis</a><div className={styles.actions}><button className="primary" disabled={busy} onClick={() => setDraft({ ...selected.data })}>Edit thesis</button><button className="secondary" disabled={busy} onClick={() => { setDraft({ ...selected.data, status: "archived" }); }}>Review archive</button><button className="secondary" disabled={busy} onClick={() => { setReviewing(true); setNextReview(selected.data.review_date ?? ""); }}>Record review</button><button className="secondary" disabled={busy} onClick={() => revisions()}>Revision history</button><button className="secondary" disabled={busy} onClick={() => askAssistantToDraft(selected.data.symbol)}>Ask assistant to draft</button></div></article> : <div className={styles.card}><h2>Your research, kept together</h2><p>Select a thesis or create one. Your notes stay private to your account.</p></div>}
      {reviewing && selected && <section className={styles.card}><h2>Record your review</h2><p>Confirm that you reviewed this thesis. Previous reasoning and revisions remain available.</p><form className={styles.form} onSubmit={recordReview}><label>Next review date<input type="date" value={nextReview} onChange={event => setNextReview(event.target.value)} /></label><div className={styles.actions}><button className="primary" disabled={busy}>Confirm reviewed</button><button type="button" className="secondary" disabled={busy} onClick={() => setReviewing(false)}>Cancel review</button></div></form></section>}
      {history && <details className={`${styles.card} ${styles.revisionHistory}`} open={historyOpen} onToggle={event => setHistoryOpen(event.currentTarget.open)}><summary>Full revision history</summary>{history.items.map(item => <details key={item.revision}><summary>Revision {item.revision} · {new Date(item.recorded_at).toLocaleString()}</summary><h3>{item.data.title}</h3><p>{item.data.symbol} · {item.data.asset_type.toUpperCase()} · {item.data.identity?.display_name}</p><p>Status: {item.data.status} · Review date: {item.data.review_date ?? "Not set"}{item.data.reviewed_at ? ` · Reviewed ${new Date(item.data.reviewed_at).toLocaleString()}` : ""}</p><h4>My thesis</h4><p>{item.data.reasoning || "No reasoning recorded."}</p><h4>Risks</h4><p>{item.data.risks || "No risks recorded."}</p><h4>What would change my mind</h4><p>{item.data.invalidation || "No invalidation conditions recorded."}</p><h4>Evidence</h4>{item.data.evidence.length ? <ul>{item.data.evidence.map((evidence, index) => <li key={index}>{evidence.kind} · {evidence.reference}{evidence.excerpt && <p>{evidence.excerpt}</p>}</li>)}</ul> : <p>No evidence attached.</p>}</details>)}<div className={styles.actions}><button className="secondary" disabled={historyPage === 1 || busy} onClick={() => revisions(historyPage - 1)}>Previous revisions</button><button className="secondary" disabled={!history.has_next || busy} onClick={() => revisions(historyPage + 1)}>Older revisions</button></div></details>}
    </section></div>
  </main>;
}
