/* DOM construction uses textContent throughout so provider/history strings cannot inject markup. */
"use strict";

const apiRoot = "/api/v1";
const forecastForm = document.querySelector("#forecast-form");
const resultContent = document.querySelector("#result-content");
const qualityBadge = document.querySelector("#quality-badge");
const announcement = document.querySelector("#announcement");
const historyContent = document.querySelector("#history-content");
const historyForm = document.querySelector("#history-form");
const symbolInput = document.querySelector("#symbol");
const lookupStatus = document.querySelector("#lookup-status");
const instrumentOptions = document.querySelector("#instrument-options");
const identityConfirmation = document.querySelector("#identity-confirmation");
const freshAnalysisSection = document.querySelector("#fresh-analysis-section");
const freshAnalysisContent = document.querySelector("#fresh-analysis-content");
let historyPage = 1;
let selectedIdentity = null;
let lookupTimer = null;
let lookupController = null;
let lookupSequence = 0;
let activeOption = -1;
const runRelationPageSize = 100;
const runRelationMaxPages = 5;
const runRelationMaxLookups = 10;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatPercent(value) {
  return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function formatPrice(value, currency) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
}

function formatTime(value) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function formatNumber(value, digits = 4) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value);
}

function contractLabel(value) {
  const labels = {
    brier_score: "Brier score",
    baseline_brier_score: "Baseline Brier score",
    confidence_level: "Confidence level",
    interval_coverage: "Interval coverage",
    sample_size: "Sample count",
    walk_forward: "Chronological walk-forward",
  };
  const label = labels[value] || value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
  return label.replace(/\bbrier\b/i, "Brier").replace(/\bewma\b/i, "EWMA");
}

function contractValue(key, value) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value !== "number") return String(value);
  if (/(?:probability|frequency|coverage|confidence_level|calibration_error|^low$|^high$|^level$)$/.test(key)) {
    return formatPercent(value);
  }
  if (key.includes("percent")) return `${formatNumber(value, 2)}%`;
  return formatNumber(value);
}

function appendContractRows(body, value, prefix = "") {
  // Evaluation and uncertainty records are versioned server data. Flattening their bounded
  // objects keeps every metric available as text without coupling the UI to one chart shape.
  for (const [key, item] of Object.entries(value || {})) {
    const path = prefix ? `${prefix} · ${contractLabel(key)}` : contractLabel(key);
    if (item === null || item === undefined || item === "") continue;
    if (Array.isArray(item)) {
      if (item.every((entry) => ["string", "number", "boolean"].includes(typeof entry))) {
        tableRow(body, path, item.map((entry) => contractValue(key, entry)).join("; "));
      } else {
        item.forEach((entry, index) => appendContractRows(body, entry, `${path} ${index + 1}`));
      }
    } else if (typeof item === "object") {
      appendContractRows(body, item, path);
    } else {
      tableRow(body, path, contractValue(key, item));
    }
  }
}

function contractSection(title, className, value) {
  if (!value || (typeof value === "object" && !Object.keys(value).length)) return null;
  const section = element("section", className);
  section.append(element("h4", "", title));
  const table = element("table", "details-table contract-table");
  table.append(element("caption", "sr-only", `${title} details`));
  const body = document.createElement("tbody");
  appendContractRows(body, value);
  table.append(body);
  section.append(table);
  return section;
}

function compactReliability(reliability) {
  if (!reliability) return null;
  const populated = (bins) => (bins || []).filter((bin) => bin.count > 0);
  const binText = (bin) => (
    `${formatPercent(bin.low)}–${formatPercent(bin.high)}: ${bin.count} samples, `
    + `mean predicted ${formatPercent(bin.mean_predicted_probability)}, observed ${formatPercent(bin.observed_frequency)}`
  );
  return {
    bin_count: reliability.bin_count,
    empty_bins: "Empty fixed-width bins are omitted below; all populated calibration bins are shown.",
    direction: Object.fromEntries(
      Object.entries(reliability.direction || {}).map(([direction, bins]) => (
        [direction, populated(bins).map(binText)]
      )),
    ),
    thresholds: Object.fromEntries((reliability.thresholds || []).map((item) => {
      const sign = item.threshold > 0 ? "+" : "";
      return [`${item.operator}_${sign}${item.threshold}_percent`, populated(item.bins).map(binText)];
    })),
  };
}

function compactEvaluationScores(scores) {
  if (!scores) return null;
  return {
    name: scores.name,
    version: scores.version,
    definition: scores.definition,
    direction_Brier: scores.direction_brier,
    threshold_Brier: (scores.threshold_brier || []).map((item) => (
      `${item.operator} ${item.threshold > 0 ? "+" : ""}${item.threshold}%: ${formatNumber(item.score)}`
    )),
    reliability: compactReliability(scores.reliability),
    interval_coverage: (scores.interval_coverage || []).map((item) => (
      `${formatPercent(item.level)}: ${item.covered_count}/${item.sample_count}, ${formatPercent(item.coverage)}; ${item.definition}`
    )),
  };
}

function compactEvaluation(evaluation) {
  if (!evaluation) return null;
  // Empty calibration bins carry no estimate. Summarizing them avoids hundreds of redundant
  // table rows while retaining every populated model/baseline bin and its text values.
  return {
    version: evaluation.version,
    method: evaluation.method,
    status: evaluation.status,
    reason: evaluation.reason,
    evaluation_count: evaluation.evaluation_count,
    eligible_realized_count: evaluation.eligible_realized_count,
    excluded_anomaly_outcome_count: evaluation.excluded_anomaly_outcome_count,
    date_range: evaluation.date_range,
    training_sample_range: evaluation.training_sample_range,
    forecast_model: compactEvaluationScores(evaluation.forecast_model),
    baseline: compactEvaluationScores(evaluation.baseline),
    maximum_evaluation_points: evaluation.max_evaluation_points,
    minimum_training_samples: evaluation.minimum_training_samples,
    information_rule: evaluation.information_rule,
  };
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${apiRoot}${path}`, {
    ...options,
    headers,
  });
  let body;
  try {
    body = await response.json();
  } catch (_) {
    // A proxy or interrupted local process may return non-JSON; keep that failure safe to render.
    body = { error: { code: "invalid_response", message: "The local service returned an invalid response." } };
  }
  if (!response.ok) {
    const error = new Error(body.error?.message || body.detail || "Local service request failed.");
    error.code = body.error?.code || "request_failed";
    error.requestId = body.error?.request_id || "";
    throw error;
  }
  return body;
}

function tableRow(table, label, value) {
  const row = table.insertRow();
  const heading = document.createElement("th");
  heading.scope = "row";
  heading.textContent = label;
  row.append(heading, element("td", "", value));
}

function identityValue(identity, key) {
  const value = identity?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function hideOptions() {
  activeOption = -1;
  instrumentOptions.hidden = true;
  instrumentOptions.replaceChildren();
  symbolInput.setAttribute("aria-expanded", "false");
  symbolInput.removeAttribute("aria-activedescendant");
}

function clearIdentity() {
  selectedIdentity = null;
  identityConfirmation.hidden = true;
  identityConfirmation.replaceChildren();
}

function confirmIdentity(identity) {
  const symbol = identityValue(identity, "canonical_symbol");
  if (!symbol) return;
  selectedIdentity = identity;
  symbolInput.value = symbol;
  const assetControl = forecastForm.querySelector(
    `input[name="asset_type"][value="${identity.asset_type}"]`,
  );
  if (assetControl) assetControl.checked = true;
  const title = identityValue(identity, "display_name") || identityValue(identity, "company_name");
  const details = [
    symbol,
    identityValue(identity, "exchange"),
    identityValue(identity, "currency"),
    identityValue(identity, "timezone"),
    identityValue(identity, "asset_type")?.toUpperCase(),
  ].filter(Boolean).join(" / ");
  identityConfirmation.replaceChildren(
    element("strong", "", title || symbol),
    element("span", "", ` Confirmed identity: ${details}`),
  );
  identityConfirmation.hidden = false;
  lookupStatus.textContent = `Selected ${title || symbol}.`;
  hideOptions();
}

function setActiveOption(index) {
  const options = [...instrumentOptions.querySelectorAll("[role=option]")];
  if (!options.length) return;
  activeOption = Math.max(0, Math.min(index, options.length - 1));
  options.forEach((option, optionIndex) => {
    option.setAttribute("aria-selected", String(optionIndex === activeOption));
  });
  symbolInput.setAttribute("aria-activedescendant", options[activeOption].id);
  options[activeOption].scrollIntoView({ block: "nearest" });
}

function renderInstrumentOptions(items, query) {
  instrumentOptions.replaceChildren();
  activeOption = -1;
  if (!items.length) {
    hideOptions();
    lookupStatus.textContent = `No identity matches “${query}”; a valid typed symbol can still be submitted.`;
    return;
  }
  items.forEach((identity, index) => {
    const option = element("li", "instrument-option");
    option.id = `instrument-option-${lookupSequence}-${index}`;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", "false");
    const name = identityValue(identity, "display_name") || identityValue(identity, "company_name");
    const facts = [
      identityValue(identity, "canonical_symbol"),
      identityValue(identity, "exchange"),
      identityValue(identity, "currency"),
      identityValue(identity, "asset_type")?.toUpperCase(),
    ].filter(Boolean).join(" / ");
    option.append(element("strong", "", name || identity.canonical_symbol), element("span", "", facts));
    option.addEventListener("mousedown", (event) => event.preventDefault());
    option.addEventListener("click", () => confirmIdentity(identity));
    instrumentOptions.append(option);
  });
  instrumentOptions.hidden = false;
  symbolInput.setAttribute("aria-expanded", "true");
  lookupStatus.textContent = `${items.length} bounded identity ${items.length === 1 ? "match" : "matches"}. Use arrow keys and Enter to select.`;
}

async function lookupInstruments(query) {
  lookupSequence += 1;
  const sequence = lookupSequence;
  if (lookupController) lookupController.abort();
  const controller = new AbortController();
  lookupController = controller;
  lookupStatus.textContent = `Looking up “${query}”…`;
  try {
    const data = await api(`/instruments?${new URLSearchParams({ query, limit: "5" })}`, {
      signal: controller.signal,
    });
    // Sequence and current text checks prevent an older response from replacing newer choices.
    if (sequence !== lookupSequence || symbolInput.value.trim() !== query) return null;
    renderInstrumentOptions(data.items.slice(0, 5), query);
    return data.items.slice(0, 5);
  } catch (error) {
    if (error.name === "AbortError" || sequence !== lookupSequence) return null;
    hideOptions();
    lookupStatus.textContent = `Identity lookup unavailable: ${error.message}`;
    return null;
  } finally {
    if (lookupController === controller) lookupController = null;
  }
}

function cancelPendingLookup() {
  // A direct-symbol forecast supersedes suggestions: invalidate callbacks before aborting so the
  // expected cancellation cannot render an identity error or stale choices over the forecast.
  clearTimeout(lookupTimer);
  lookupTimer = null;
  lookupSequence += 1;
  if (lookupController) lookupController.abort();
  lookupController = null;
}

symbolInput.addEventListener("input", () => {
  cancelPendingLookup();
  clearIdentity();
  hideOptions();
  const query = symbolInput.value.trim();
  if (query.length < 2) {
    lookupStatus.textContent = query ? "Type at least 2 characters for identity choices." : "";
    return;
  }
  // A short debounce and API limit cap provider work while still supporting ordinary typing.
  lookupTimer = setTimeout(() => lookupInstruments(query), 300);
});

symbolInput.addEventListener("keydown", (event) => {
  const options = [...instrumentOptions.querySelectorAll("[role=option]")];
  if (instrumentOptions.hidden || !options.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    setActiveOption(activeOption + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setActiveOption(activeOption <= 0 ? options.length - 1 : activeOption - 1);
  } else if (event.key === "Enter" && activeOption >= 0) {
    event.preventDefault();
    options[activeOption].click();
  } else if (event.key === "Escape") {
    event.preventDefault();
    hideOptions();
  }
});

forecastForm.querySelectorAll('input[name="asset_type"]').forEach((control) => {
  control.addEventListener("change", () => {
    if (selectedIdentity && control.value !== selectedIdentity.asset_type) {
      clearIdentity();
      lookupStatus.textContent = "Asset type changed; confirm the instrument identity again.";
    }
  });
});

function renderForecastCard(result, input) {
  const card = element("article", "forecast-card");
  card.dataset.horizon = result.horizon;
  const header = element("header", "card-head");
  header.append(
    element("span", "data-label", result.horizon === "close_to_close" ? "Daily horizon" : "Intraday horizon"),
    element("h3", "", result.horizon === "close_to_close" ? "Close → next close" : "Completed 5m → close"),
    element("p", "", result.definition),
  );
  card.append(header);

  const probabilities = result.direction_probabilities;
  const chart = element("div", "probability-chart");
  chart.setAttribute("role", "img");
  chart.setAttribute("aria-label", `Down ${formatPercent(probabilities.down)}, unchanged ${formatPercent(probabilities.flat)}, up ${formatPercent(probabilities.up)}`);
  for (const direction of ["down", "flat", "up"]) {
    const bar = element("div", `probability-bar ${direction}`);
    // A native meter avoids CSP-blocked inline styles while preserving a numeric value.
    const fill = element("meter", "fill");
    fill.min = 0;
    fill.max = 1;
    fill.value = probabilities[direction];
    fill.textContent = formatPercent(probabilities[direction]);
    const directionLabel = direction === "flat" ? "unchanged" : direction;
    bar.append(element("span", "value", formatPercent(probabilities[direction])), fill, element("span", "label", directionLabel));
    chart.append(bar);
  }
  card.append(chart);

  // The tables duplicate every visual value and retain definitions/units for non-visual use.
  const table = element("table", "details-table");
  table.append(element("caption", "", "Horizon, direction, and threshold details"));
  const body = document.createElement("tbody");
  table.append(body);
  tableRow(body, "Origin price", formatPrice(result.origin_price, input.currency));
  tableRow(body, "Origin timestamp", formatTime(result.origin_timestamp));
  tableRow(body, "Reference timestamp", formatTime(result.reference_timestamp || result.origin_timestamp));
  tableRow(body, "Reference state", contractLabel(result.reference_state || "reported_origin"));
  tableRow(body, "Target close", formatTime(result.target_timestamp));
  tableRow(body, "Target state", contractLabel(result.target_state || "scheduled_session_close"));
  tableRow(body, "Session at request", contractLabel(result.session_state_at_request || input.session_state_at_request));
  tableRow(body, "Session semantics", result.target_session_rule || input.session_rule);
  tableRow(body, "Calculated at", formatTime(result.calculated_at));
  if (result.origin_bar_end) {
    tableRow(
      body,
      "Completed-bar evidence",
      `Selected five-minute bar ended ${formatTime(result.origin_bar_end)}, at or before request cutoff ${formatTime(input.request_cutoff)}; an active incomplete bar is excluded.`,
    );
  }
  const definitions = probabilities.definitions || {};
  tableRow(body, "Down probability", `${formatPercent(probabilities.down)} · ${definitions.down || "return below the flat range"}`);
  tableRow(body, "Unchanged probability", `${formatPercent(probabilities.flat)} · ${definitions.flat || probabilities.flat_definition}`);
  tableRow(body, "Up probability", `${formatPercent(probabilities.up)} · ${definitions.up || "return above the flat range"}`);
  for (const threshold of result.threshold_probabilities) {
    const operator = threshold.operator === "lte" ? "at or below" : "at or above";
    const signedThreshold = `${threshold.threshold > 0 ? "+" : ""}${threshold.threshold.toFixed(0)}%`;
    const details = [
      formatPercent(threshold.probability),
      threshold.definition,
      threshold.sample_count === undefined
        ? null
        : `${threshold.event_count} events / ${threshold.sample_count} samples`,
      threshold.rare_event === undefined ? null : `rare-event flag: ${threshold.rare_event ? "yes" : "no"}`,
      threshold.uncertainty
        ? `${formatPercent(threshold.uncertainty.level)} ${threshold.uncertainty.method} uncertainty: ${formatPercent(threshold.uncertainty.low)} to ${formatPercent(threshold.uncertainty.high)}`
        : threshold.uncertainty_method,
    ].filter(Boolean).join(" · ");
    tableRow(body, `Return ${operator} ${signedThreshold}`, details);
  }
  const conditional = contractSection(
    "Conditional gain / loss magnitudes",
    "conditional-details",
    result.conditional_magnitudes || result.conditional_probabilities || result.conditional_gain_loss,
  );
  if (conditional) card.append(table, conditional);
  else card.append(table);

  const intervalTable = element("table", "details-table interval-table");
  intervalTable.append(element("caption", "", "Return and price intervals"));
  const intervalBody = document.createElement("tbody");
  intervalTable.append(intervalBody);
  for (const interval of result.magnitude_intervals) {
    tableRow(
      intervalBody,
      `${formatPercent(interval.level)} magnitude interval (return and price)`,
      `${interval.definition}: ${interval.percent.low.toFixed(2)}% to ${interval.percent.high.toFixed(2)} percent return (${interval.percent.unit}); ${formatPrice(interval.price.low, input.currency)} to ${formatPrice(interval.price.high, input.currency)} (${interval.price.unit})`,
    );
  }
  tableRow(intervalBody, "Model", `${result.model?.name || input.model.name} / ${result.model?.version || result.model_version || input.model.version}`);
  tableRow(intervalBody, "Forecast contract", result.forecast_contract_version || input.forecast_contract_version);
  tableRow(intervalBody, "Model fingerprint", result.model_fingerprint || input.model_fingerprint);
  tableRow(intervalBody, "Forecast fingerprint", result.forecast_fingerprint);
  tableRow(intervalBody, "Historical sample count", String(result.sample_size));
  tableRow(intervalBody, "Distribution", result.distribution_definition);
  card.append(intervalTable);

  const uncertainty = contractSection(
    "Sample uncertainty",
    "uncertainty-details",
    result.uncertainty || result.rare_event_uncertainty || {
      direction_event_counts: probabilities.event_counts,
      direction_Wilson_intervals: probabilities.uncertainty,
      sample_accounting: result.sample_accounting,
      probability_estimator: result.probability_estimator,
    },
  );
  if (uncertainty) card.append(uncertainty);
  const evaluation = contractSection(
    "Chronological walk-forward evaluation",
    "evaluation-details",
    compactEvaluation(
      result.evaluation || input.evaluations?.[result.horizon] || input.evaluation?.[result.horizon],
    ),
  );
  if (evaluation) card.append(evaluation);

  if (result.outcomes?.length) {
    const outcomes = element("section", "outcomes");
    outcomes.append(
      element("h4", "", "Append-only outcome ledger"),
      element("p", "outcome-note", "Later observations and corrections are additional entries. They never replace this recorded forecast or an earlier outcome."),
    );
    const outcomeList = element("ol", "outcome-list");
    for (const outcome of result.outcomes) {
      const observed = outcome.observed_close === null
        ? "Close unavailable"
        : `${formatPrice(outcome.observed_close, input.currency)}; ${formatPercent(outcome.observed_return)}`;
      const item = element("li");
      item.append(
        element("span", "outcome-state", outcome.state),
        document.createTextNode(`observed ${formatTime(outcome.observed_at)} — ${observed}. ${outcome.note || "No note."} Appended ${formatTime(outcome.created_at || outcome.recorded_at || outcome.observed_at)}.`),
      );
      outcomeList.append(item);
    }
    outcomes.append(outcomeList);
    if (result.outcomes_truncated) {
      outcomes.append(element("p", "outcome-note", "Only the newest 100 outcome entries are shown; the append-only ledger contains earlier entries."));
    }
    card.append(outcomes);
  }
  return card;
}

function renderResult(data, context = "live") {
  const input = data.input;
  resultContent.setAttribute("aria-busy", "false");
  resultContent.className = "";
  resultContent.replaceChildren();
  qualityBadge.className = `badge ${data.repeated ? "repeated" : input.quality}`;
  qualityBadge.textContent = data.repeated ? `Repeated / ${input.quality}` : input.quality;

  const stateStrip = element(
    "p",
    "state-strip",
    context === "saved"
      ? `Immutable recorded result · audit event #${data.event.id}. Forecast inputs and values are reopened exactly as saved; append-only outcomes are shown separately below.`
      : data.repeated
        ? `Repeated request recorded as audit event #${data.event.id}; ${data.reused ? "the identical saved forecast was reused." : "new provider input created a new immutable run."}`
        : `Successful request recorded as audit event #${data.event.id}.`,
  );
  resultContent.append(stateStrip);

  const meta = element("div", "forecast-meta");
  const fields = [
    ["Display name", input.display_name],
    ["Company name", input.company_name],
    ["Canonical symbol", input.canonical_symbol || input.symbol],
    ["Instrument type", [input.asset_type?.toUpperCase(), input.quote_type].filter(Boolean).join(" / ")],
    ["Exchange", input.exchange],
    ["Currency", input.currency],
    ["Exchange timezone", input.exchange_timezone],
    ["Provider as-of", formatTime(input.provider_as_of)],
    ["Calculated", formatTime(input.captured_at)],
    ["Source", input.provider],
    ["Model", `${input.model.name} / ${input.model.version}`],
  ];
  for (const [label, value] of fields.filter(([, value]) => value !== null && value !== undefined && value !== "")) {
    const cell = element("div");
    cell.append(element("span", "data-label", label), element("strong", "", value));
    meta.append(cell);
  }
  resultContent.append(meta);
  const grid = element("div", "forecast-grid");
  for (const result of data.results) grid.append(renderForecastCard(result, input));
  resultContent.append(grid);
  const provenance = element("aside", "provenance");
  provenance.setAttribute("aria-label", "Forecast provenance and quality");
  provenance.append(element("h3", "", "Data quality, limitations, and provenance"));
  const providerLimitations = [
    ...(Array.isArray(input.provider_limitations) ? input.provider_limitations : []),
    ...(Array.isArray(input.archive_limitations) ? input.archive_limitations : []),
    ...(Array.isArray(input.provenance?.provider_limitations) ? input.provenance.provider_limitations : []),
  ];
  for (const key of ["archive_limitation", "intraday_archive_limitation"]) {
    const limitation = input.provider_metadata?.[key] || input.provenance?.[key];
    if (limitation) providerLimitations.push(limitation);
  }
  const intradayArchive = input.provider_metadata?.intraday_archive_limit;
  if (intradayArchive?.statement) providerLimitations.push(intradayArchive.statement);
  if (!providerLimitations.some((item) => /archive|60.day/i.test(String(item)))) {
    // Yahoo documents a moving intraday-history window; this product constraint remains visible
    // even when a deterministic fixture has no remote archive response to report.
    providerLimitations.push(
      "Yahoo Finance five-minute history has an approximate 60-day archive limit; older intraday reconstruction may be unavailable.",
    );
  }
  const limitations = [...new Set([...(input.limitations || []), ...providerLimitations])];
  const missing = Object.fromEntries(
    Object.entries(input.provider_metadata || {}).filter(([key]) => key.includes("missing")),
  );
  provenance.append(
    element("p", "", `Provider: ${input.provider}. Response as-of: ${formatTime(input.provider_as_of)}.`),
    element("p", "", `Stale state: ${input.stale_state?.state || input.quality}. ${(input.quality_reasons || input.stale_state?.reasons || []).join("; ") || "No stale-data reasons reported."}`),
    element("p", "", `Session at request: ${contractLabel(input.session_state_at_request)}. Session rule: ${input.session_rule}`),
    element("p", "", `Calendar: ${input.calendar.name} / ${input.calendar.version} / ${input.calendar.timezone}.`),
    element("p", "", `Captured prices: ${input.selected_daily_bars.length} daily closes and ${input.selected_intraday_bars.length} completed intraday bars.`),
    element("p", "", `Missing data: ${Object.keys(missing).length ? "provider missing-data counters follow." : "no missing bars or scheduled closes reported."}`),
    element("p", "", `Limitations, including archive availability: ${limitations.join(" ") || "No provider limitations reported."}`),
    element("p", "", `Content fingerprint: ${input.content_fingerprint}`),
    element("p", "", `Audit event #${data.event.id}${data.reused ? " references an identical immutable forecast run." : " records a new immutable forecast run."}`),
  );
  const missingSection = contractSection(
    "Missing-bar evidence",
    "missing-details",
    { ...missing, ...(input.missing_data || {}) },
  );
  if (missingSection) provenance.append(missingSection);
  const coverageSection = contractSection(
    "Returned provider coverage and archive semantics",
    "coverage-details",
    {
      session_scope: input.provider_metadata?.session_scope,
      daily_coverage: input.provider_metadata?.daily_coverage,
      intraday_coverage: input.provider_metadata?.intraday_coverage,
      intraday_archive_limit: input.provider_metadata?.intraday_archive_limit,
    },
  );
  if (coverageSection) provenance.append(coverageSection);
  const providerEvidence = contractSection(
    "Provider request and immutable provenance",
    "provider-details",
    input.provenance || {
      source: input.provider,
      query: input.provider_query,
      response_as_of: input.provider_as_of,
      content_fingerprint: input.content_fingerprint,
    },
  );
  if (providerEvidence) provenance.append(providerEvidence);
  resultContent.append(provenance);
}

function renderError(error) {
  qualityBadge.className = "badge failed";
  qualityBadge.textContent = "Failed";
  const panel = element("div", "error-panel");
  panel.setAttribute("role", "alert");
  panel.append(
    element("h3", "", "Forecast unavailable"),
    element("p", "", error.message),
    element("p", "data-label", `Error code: ${error.code || "request_failed"}`),
  );
  if (error.requestId) panel.append(element("p", "data-label", `Audit request: ${error.requestId}`));
  resultContent.setAttribute("aria-busy", "false");
  resultContent.className = "";
  resultContent.replaceChildren(panel);
}

function focusResultSection() {
  const section = document.querySelector("#result-section");
  // Moving focus dismisses a mobile keyboard and makes the newly rendered result visible.
  section.focus();
  section.scrollIntoView({ block: "start" });
}

forecastForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const symbolError = document.querySelector("#symbol-error");
  const typedQuery = symbolInput.value.trim();
  const symbol = typedQuery.toUpperCase();
  cancelPendingLookup();
  hideOptions();
  if (!/^[A-Z0-9.^-]{1,15}$/.test(symbol)) {
    const matches = await lookupInstruments(typedQuery);
    symbolError.textContent = matches?.length
      ? "Choose a matching instrument before running a forecast."
      : "Enter a 1-15 character symbol or choose a company-name match.";
    symbolInput.setAttribute("aria-invalid", "true");
    symbolInput.focus();
    return;
  }
  symbolError.textContent = "";
  symbolInput.removeAttribute("aria-invalid");
  if (!selectedIdentity || selectedIdentity.canonical_symbol !== symbol) lookupStatus.textContent = "";
  const submit = document.querySelector("#forecast-submit");
  submit.disabled = true;
  submit.querySelector("span").textContent = "Calculating…";
  resultContent.className = "empty-state loading";
  resultContent.setAttribute("aria-busy", "true");
  resultContent.replaceChildren(element("p", "", `Retrieving completed bars for ${symbol}…`));
  announcement.textContent = `Loading forecast for ${symbol}.`;
  try {
    const data = await api("/forecasts", {
      method: "POST",
      body: JSON.stringify({ symbol, asset_type: new FormData(forecastForm).get("asset_type") }),
    });
    renderResult(data);
    announcement.textContent = `Forecast ready for ${symbol}.`;
    focusResultSection();
  } catch (error) {
    renderError(error);
    announcement.textContent = `Forecast failed: ${error.message}`;
    focusResultSection();
  } finally {
    submit.disabled = false;
    submit.querySelector("span").textContent = "Run forecast";
    await loadHistory();
  }
});

async function showHistoryEvent(id, isFailure = false) {
  announcement.textContent = `Loading immutable recorded result for audit event ${id}.`;
  try {
    const data = await api(isFailure ? `/history/${id}` : `/saved-forecasts/${id}`);
    if (data.input) {
      data.repeated = data.event.status === "repeated";
      renderResult(data, "saved");
      focusResultSection();
      announcement.textContent = `Immutable recorded result ${id} reopened without recalculation.`;
    } else {
      renderError({ code: data.event.error_code, message: data.event.error_message });
      focusResultSection();
      announcement.textContent = `Historical failure ${id} loaded.`;
    }
  } catch (error) {
    renderError(error);
    announcement.textContent = `Historical event could not be loaded: ${error.message}`;
    focusResultSection();
  }
}

async function runFreshAnalysis(id) {
  // Fresh analysis has a dedicated region so it can never silently replace the saved output.
  freshAnalysisSection.hidden = false;
  freshAnalysisContent.className = "empty-state loading";
  freshAnalysisContent.setAttribute("aria-busy", "true");
  freshAnalysisContent.replaceChildren(element("p", "", `Calculating a fresh analysis at audit event #${id}’s historical cutoff…`));
  announcement.textContent = `Fresh historical-cutoff analysis for event ${id} is running.`;
  freshAnalysisSection.focus();
  try {
    // Resolve the cutoff from the server-owned snapshot; browser controls never fabricate it.
    const saved = await api(`/saved-forecasts/${id}`);
    const response = await api(`/history/${id}/reconstructions`, {
      method: "POST",
      body: JSON.stringify({
        analysis_kind: "fresh_historical_reconstruction",
        cutoff: saved.input.request_cutoff,
      }),
    });
    const data = response.analysis || response;
    freshAnalysisContent.className = "";
    freshAnalysisContent.setAttribute("aria-busy", "false");
    freshAnalysisContent.replaceChildren();
    const cutoff = data.input?.request_cutoff || response.request_cutoff;
    freshAnalysisContent.append(element(
      "p",
      "state-strip",
      `Fresh analysis${data.event?.id ? ` recorded as new audit event #${data.event.id}` : ""}${cutoff ? ` at historical cutoff ${formatTime(cutoff)}` : ""}. This is a new calculation, not the immutable saved forecast above.`,
    ));
    if (!data.input || !data.results) throw new Error("Fresh analysis response omitted forecast details.");
    const meta = element("div", "forecast-meta");
    for (const [label, value] of [
      ["Historical cutoff", data.input.request_cutoff],
      ["Provider as-of", data.input.provider_as_of],
      ["Calculated", data.input.captured_at],
      ["Model", `${data.input.model.name} / ${data.input.model.version}`],
      ["Content fingerprint", data.input.content_fingerprint],
    ]) {
      const display = label.includes("cutoff") || label.includes("as-of") || label === "Calculated"
        ? formatTime(value)
        : value;
      const cell = element("div");
      cell.append(element("span", "data-label", label), element("strong", "", display));
      meta.append(cell);
    }
    freshAnalysisContent.append(meta);
    const grid = element("div", "forecast-grid");
    for (const result of data.results) grid.append(renderForecastCard(result, data.input));
    freshAnalysisContent.append(grid);
    announcement.textContent = `Fresh historical-cutoff analysis for event ${id} is ready in the separate analysis region.`;
  } catch (error) {
    freshAnalysisContent.className = "";
    freshAnalysisContent.setAttribute("aria-busy", "false");
    const panel = element("div", "error-panel");
    panel.setAttribute("role", "alert");
    panel.append(element("h3", "", "Fresh analysis unavailable"), element("p", "", error.message));
    freshAnalysisContent.replaceChildren(panel);
    announcement.textContent = `Fresh historical-cutoff analysis failed: ${error.message}`;
  }
}

function explicitRunReuse(item) {
  if (typeof item.reused === "boolean") return item.reused;
  if (item.run_disposition === "reused") return true;
  if (item.run_disposition === "new") return false;
  return null;
}

function hasPriorRunReference(item, candidates) {
  return candidates.some((candidate) => (
    candidate.id < item.id
    && candidate.run_id === item.run_id
    && candidate.status !== "failed"
  ));
}

async function persistedRunRelations(items) {
  const relations = new Map();
  const unresolvedByInstrument = new Map();
  for (const item of items) {
    if (item.status === "failed") continue;
    const explicit = explicitRunReuse(item);
    if (explicit !== null) {
      relations.set(item.id, explicit);
    } else if (item.status === "successful") {
      relations.set(item.id, false);
    } else if (item.status === "repeated" && item.is_repeat && item.run_id !== null) {
      if (hasPriorRunReference(item, items)) {
        relations.set(item.id, true);
      } else {
        const symbol = item.normalized_symbol || item.submitted_symbol;
        const key = `${item.asset_type}:${symbol}`;
        const group = unresolvedByInstrument.get(key) || { symbol, assetType: item.asset_type, items: [] };
        group.items.push(item);
        unresolvedByInstrument.set(key, group);
      }
    }
  }

  let lookups = 0;
  for (const group of unresolvedByInstrument.values()) {
    if (lookups >= runRelationMaxLookups) break;
    lookups += 1;
    const candidates = [];
    let exhausted = false;
    try {
      // Status filters can hide the first event for a run. Rebuild that relation only from
      // bounded, persisted history fields; process memory and equal timestamps are not evidence.
      for (let page = 1; page <= runRelationMaxPages; page += 1) {
        const params = new URLSearchParams({
          q: group.symbol,
          asset_type: group.assetType,
          page: String(page),
          page_size: String(runRelationPageSize),
        });
        const history = await api(`/history?${params}`);
        candidates.push(...history.items);
        if (page * history.page_size >= history.total) {
          exhausted = true;
          break;
        }
      }
      for (const item of group.items) {
        if (hasPriorRunReference(item, candidates)) {
          relations.set(item.id, true);
        } else if (exhausted) {
          // A complete bounded scan proves this repeated request created a distinct new run.
          relations.set(item.id, false);
        }
      }
    } catch (_) {
      // The row remains usable with an honest unknown relation if enrichment is unavailable.
    }
  }
  return relations;
}

function runDisposition(item, relations) {
  if (item.status === "failed") return "No forecast run";
  const reused = relations.get(item.id);
  if (reused === true) {
    return `Reused immutable run #${item.run_id}`;
  }
  if (reused === false) {
    return `New immutable run #${item.run_id}`;
  }
  return `Repeated submission · immutable run #${item.run_id} relation unavailable`;
}

function analysisLabel(item) {
  if (item.analysis_kind === "fresh_historical_reconstruction") {
    const source = item.source_event_id ? ` · source #${item.source_event_id}` : "";
    const cutoff = item.requested_cutoff ? ` · ${formatTime(item.requested_cutoff)}` : "";
    return `Fresh cutoff analysis${source}${cutoff}`;
  }
  return "Submitted forecast";
}

function renderHistory(data, runRelations) {
  historyContent.setAttribute("aria-busy", "false");
  if (!data.items.length) {
    historyContent.replaceChildren(element("p", "empty-state", "No audit events match these filters."));
  } else {
    const table = element("table", "history-table");
    const caption = element("caption", "sr-only", "Submitted forecast search history");
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");
    for (const label of ["Request / run", "Symbol", "Type", "Analysis", "Status", "Submitted", "Actions"]) {
      const heading = element("th", "", label);
      heading.scope = "col";
      headerRow.append(heading);
    }
    head.append(headerRow);
    const body = document.createElement("tbody");
    for (const item of data.items) {
      const row = document.createElement("tr");
      const requestCell = document.createElement("td");
      const runLabel = element("span", "run-label", runDisposition(item, runRelations));
      requestCell.append(
        element("span", "request-label", `New request #${item.id}`),
        runLabel,
      );
      row.append(
        requestCell,
        element("td", "", item.normalized_symbol || item.submitted_symbol || "Invalid"),
        element("td", "", item.asset_type.toUpperCase()),
        element("td", "", analysisLabel(item)),
        element("td", `status-${item.status}`, item.status),
        element("td", "", formatTime(item.submitted_at)),
      );
      const actionCell = document.createElement("td");
      actionCell.className = "history-actions";
      const action = element("button", "", item.status === "failed" ? "View failed request" : "Reopen saved forecast");
      action.type = "button";
      action.addEventListener("click", () => showHistoryEvent(item.id, item.status === "failed"));
      actionCell.append(action);
      if (item.status !== "failed") {
        const fresh = element("button", "", "Run fresh cutoff analysis");
        fresh.type = "button";
        fresh.addEventListener("click", () => runFreshAnalysis(item.id));
        actionCell.append(fresh);
      }
      row.append(actionCell);
      body.append(row);
    }
    table.append(caption, head, body);
    historyContent.replaceChildren(table);
  }
  document.querySelector("#history-page").textContent = `Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
  document.querySelector("#history-previous").disabled = data.page <= 1;
  document.querySelector("#history-next").disabled = data.page * data.page_size >= data.total;
}

async function loadHistory() {
  const values = new FormData(historyForm);
  const pageSize = ["10", "20", "50"].includes(values.get("page_size"))
    ? values.get("page_size")
    : "10";
  const params = new URLSearchParams({ page: String(historyPage), page_size: pageSize });
  if (values.get("q")) params.set("q", values.get("q"));
  if (values.get("status")) params.set("status", values.get("status"));
  if (values.get("asset_type")) params.set("asset_type", values.get("asset_type"));
  if (values.get("analysis_kind")) params.set("analysis_kind", values.get("analysis_kind"));
  const exportParams = new URLSearchParams(params);
  exportParams.delete("page");
  exportParams.delete("page_size");
  document.querySelector("#export-csv").href = `${apiRoot}/history-export.csv?${exportParams}`;
  document.querySelector("#export-json").href = `${apiRoot}/history-export.json?${exportParams}`;
  historyContent.setAttribute("aria-busy", "true");
  historyContent.replaceChildren(element("p", "history-loading", "Loading bounded audit history…"));
  try {
    const data = await api(`/history?${params}`);
    renderHistory(data, await persistedRunRelations(data.items));
  } catch (error) {
    historyContent.setAttribute("aria-busy", "false");
    const panel = element("p", "error-panel", `History unavailable: ${error.message}`);
    panel.setAttribute("role", "alert");
    historyContent.replaceChildren(panel);
  }
}

historyForm.addEventListener("submit", (event) => {
  event.preventDefault();
  historyPage = 1;
  loadHistory();
});
document.querySelector("#history-previous").addEventListener("click", () => { historyPage -= 1; loadHistory(); });
document.querySelector("#history-next").addEventListener("click", () => { historyPage += 1; loadHistory(); });

async function initialize() {
  const state = document.querySelector(".system-state");
  try {
    // Both checks stay behind /api/v1; backup filenames and storage paths never enter the page.
    const [readiness, backup] = await Promise.all([api("/readiness"), api("/operations/backups/status")]);
    state.classList.add("ready");
    document.querySelector("#system-label").textContent = `Local service ready / ${readiness.provider} / backup ${backup.status}`;
  } catch (_) {
    state.classList.add("failed");
    document.querySelector("#system-label").textContent = "Local service unavailable";
  }
  await loadHistory();
}

initialize();
