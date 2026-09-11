/* DOM construction uses textContent throughout so provider/history strings cannot inject markup. */
"use strict";

const apiRoot = "/api/v1";
const forecastForm = document.querySelector("#forecast-form");
const resultContent = document.querySelector("#result-content");
const qualityBadge = document.querySelector("#quality-badge");
const announcement = document.querySelector("#announcement");
const historyContent = document.querySelector("#history-content");
const historyForm = document.querySelector("#history-form");
let historyPage = 1;

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

function renderForecastCard(result, input) {
  const card = element("article", "forecast-card");
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
  chart.setAttribute("aria-label", `Down ${formatPercent(probabilities.down)}, flat ${formatPercent(probabilities.flat)}, up ${formatPercent(probabilities.up)}`);
  for (const direction of ["down", "flat", "up"]) {
    const bar = element("div", `probability-bar ${direction}`);
    // A native meter avoids CSP-blocked inline styles while preserving a numeric value.
    const fill = element("meter", "fill");
    fill.min = 0;
    fill.max = 1;
    fill.value = probabilities[direction];
    fill.textContent = formatPercent(probabilities[direction]);
    bar.append(element("span", "value", formatPercent(probabilities[direction])), fill, element("span", "label", direction));
    chart.append(bar);
  }
  card.append(chart);

  // The table duplicates every chart value and adds interval/threshold definitions for non-visual use.
  const table = element("table", "details-table");
  table.append(element("caption", "", "Numeric forecast details"));
  const body = document.createElement("tbody");
  table.append(body);
  tableRow(body, "Origin", `${formatPrice(result.origin_price, input.currency)} at ${formatTime(result.origin_timestamp)}`);
  tableRow(body, "Target close", formatTime(result.target_timestamp));
  tableRow(body, "Down / flat / up", `${formatPercent(probabilities.down)} / ${formatPercent(probabilities.flat)} / ${formatPercent(probabilities.up)}`);
  tableRow(body, "Flat definition", probabilities.flat_definition);
  for (const threshold of result.threshold_probabilities) {
    const operator = threshold.operator === "lte" ? "at or below" : "at or above";
    tableRow(body, `Return ${operator} ${threshold.threshold.toFixed(1)}%`, formatPercent(threshold.probability));
  }
  for (const interval of result.magnitude_intervals) {
    tableRow(
      body,
      `${formatPercent(interval.level)} magnitude interval`,
      `${interval.definition}: ${interval.percent.low.toFixed(2)}% to ${interval.percent.high.toFixed(2)} percent return; ${formatPrice(interval.price.low, input.currency)} to ${formatPrice(interval.price.high, input.currency)} in quote currency`,
    );
  }
  tableRow(body, "Historical samples", String(result.sample_size));
  card.append(table);

  if (result.outcomes?.length) {
    const outcomes = element("section", "outcomes");
    outcomes.append(element("h4", "", "Observed outcomes (appended later)"));
    const outcomeTable = element("table", "details-table");
    outcomeTable.append(element("caption", "sr-only", `Observed outcomes for ${result.horizon}`));
    const outcomeBody = document.createElement("tbody");
    for (const outcome of result.outcomes) {
      const observed = outcome.observed_close === null
        ? "Close unavailable"
        : `${formatPrice(outcome.observed_close, input.currency)}; ${formatPercent(outcome.observed_return)}`;
      tableRow(
        outcomeBody,
        `${outcome.state} at ${formatTime(outcome.observed_at)}`,
        `${observed}. ${outcome.note || "No note."}`,
      );
    }
    outcomeTable.append(outcomeBody);
    outcomes.append(outcomeTable);
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
    context === "history"
      ? `Historical reconstruction of audit event #${data.event.id}. Forecast values are the originally saved values; outcomes were appended later.`
      : data.repeated
        ? `Repeated request recorded as audit event #${data.event.id}; ${data.reused ? "the identical saved forecast was reused." : "new provider input created a new immutable run."}`
        : `Successful request recorded as audit event #${data.event.id}.`,
  );
  resultContent.append(stateStrip);

  const meta = element("div", "forecast-meta");
  const fields = [
    ["Instrument", `${input.symbol} / ${input.asset_type.toUpperCase()}`],
    ["Exchange", `${input.exchange} / ${input.exchange_timezone}`],
    ["Provider as-of", formatTime(input.provider_as_of)],
    ["Calculated", formatTime(input.captured_at)],
    ["Source", input.provider],
    ["Model", `${input.model.name} / ${input.model.version}`],
  ];
  for (const [label, value] of fields) {
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
  provenance.append(
    element("p", "", `Quality: ${input.quality}. ${input.quality_reasons.join("; ") || "No stale-data flags."}`),
    element("p", "", `Session rule: ${input.session_rule}`),
    element("p", "", `Calendar: ${input.calendar.name} / ${input.calendar.version}`),
    element("p", "", `Captured prices: ${input.selected_daily_bars.length} daily closes and ${input.selected_intraday_bars.length} completed intraday bars.`),
    element("p", "", `Provider request: ${JSON.stringify(input.provider_query)}`),
    element("p", "", `Limitations: ${input.limitations.join(" ")}`),
    element("p", "", `Content fingerprint: ${input.content_fingerprint}`),
    element("p", "", `Audit event #${data.event.id}${data.reused ? " references an identical immutable forecast run." : " records a new immutable forecast run."}`),
  );
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
  const symbolInput = document.querySelector("#symbol");
  const symbolError = document.querySelector("#symbol-error");
  const symbol = symbolInput.value.trim().toUpperCase();
  if (!/^[A-Z0-9.^-]{1,15}$/.test(symbol)) {
    symbolError.textContent = "Enter 1-15 letters, numbers, '.', '-', or '^'.";
    symbolInput.setAttribute("aria-invalid", "true");
    symbolInput.focus();
    return;
  }
  symbolError.textContent = "";
  symbolInput.removeAttribute("aria-invalid");
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

async function showHistoryEvent(id) {
  announcement.textContent = `Loading historical audit event ${id}.`;
  try {
    const data = await api(`/history/${id}`);
    if (data.input) {
      data.repeated = data.event.status === "repeated";
      renderResult(data, "history");
      focusResultSection();
      announcement.textContent = `Historical reconstruction ${id} loaded.`;
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

function renderHistory(data) {
  historyContent.setAttribute("aria-busy", "false");
  if (!data.items.length) {
    historyContent.replaceChildren(element("p", "empty-state", "No audit events match these filters."));
  } else {
    const table = element("table", "history-table");
    const caption = element("caption", "sr-only", "Submitted forecast search history");
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");
    for (const label of ["Event", "Symbol", "Type", "Status", "Submitted", "Details"]) {
      const heading = element("th", "", label);
      heading.scope = "col";
      headerRow.append(heading);
    }
    head.append(headerRow);
    const body = document.createElement("tbody");
    for (const item of data.items) {
      const row = document.createElement("tr");
      row.append(
        element("td", "", `#${item.id}`),
        element("td", "", item.normalized_symbol || item.submitted_symbol || "Invalid"),
        element("td", "", item.asset_type.toUpperCase()),
        element("td", `status-${item.status}`, item.status),
        element("td", "", formatTime(item.submitted_at)),
      );
      const actionCell = document.createElement("td");
      const action = element("button", "", item.status === "failed" ? "View failure" : "Reconstruct");
      action.type = "button";
      action.addEventListener("click", () => showHistoryEvent(item.id));
      actionCell.append(action);
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
  const params = new URLSearchParams({ page: String(historyPage), page_size: "10" });
  const values = new FormData(historyForm);
  if (values.get("q")) params.set("q", values.get("q"));
  if (values.get("status")) params.set("status", values.get("status"));
  if (values.get("asset_type")) params.set("asset_type", values.get("asset_type"));
  document.querySelector("#export-link").href = `${apiRoot}/history-export.csv?${params}`;
  historyContent.setAttribute("aria-busy", "true");
  historyContent.replaceChildren(element("p", "history-loading", "Loading bounded audit history…"));
  try {
    renderHistory(await api(`/history?${params}`));
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
