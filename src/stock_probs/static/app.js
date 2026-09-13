/* textContent protects provider/history strings from markup injection. */
"use strict";

const apiRoot = "/api/v1";
const $ = (selector) => document.querySelector(selector);
const forecastForm = $("#forecast-form");
const resultContent = $("#result-content");
const qualityBadge = $("#quality-badge");
const announcement = $("#announcement");
const historyContent = $("#history-content");
const historyForm = $("#history-form");
const symbolInput = $("#symbol");
const lookupStatus = $("#lookup-status");
const optionsBox = $("#instrument-options");
const identityBox = $("#identity-confirmation");
const freshSection = $("#fresh-analysis-section");
const freshContent = $("#fresh-analysis-content");
const symbolError = $("#symbol-error");
const historyPrevious = $("#history-previous");
const historyNext = $("#history-next");
let historyPage = 1;
let selectedIdentity = null;
let lookupTimer = null;
let lookupRequest = null;
let lookupSequence = 0;
let activeOption = -1;
let chartSequence = 0;
let newsRequest = null;
let historySequence = 0;
let selectionSequence = 0;
let lastPage = 1;
let freshInFlight = false;
const newsTimeoutMs = 10_000;
const runRelationPageSize = 100;
const runRelationMaxPages = 5;
const runRelationMaxLookups = 10;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showContent(content, className, busy, ...children) {
  content.className = className;
  content.setAttribute("aria-busy", String(busy));
  content.replaceChildren(...children);
}

function disclosure(summary, className, ...children) {
  const details = element("details", className);
  details.append(element("summary", "", summary), ...children);
  return details;
}

function svgElement(tag, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
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
  const body = element("tbody");
  appendContractRows(body, value);
  table.append(body);
  section.append(table);
  return section;
}

function compactReliability(reliability) {
  if (!reliability) return null;
  const populated = (bins) => (bins || []).filter((bin) => bin.count > 0).map((bin) => (
    `${formatPercent(bin.low)}–${formatPercent(bin.high)}: ${bin.count} samples, mean predicted ${formatPercent(bin.mean_predicted_probability)}, observed ${formatPercent(bin.observed_frequency)}`
  ));
  return {
    bin_count: reliability.bin_count,
    empty_bins: "Empty fixed-width bins are omitted below; all populated calibration bins are shown.",
    direction: Object.fromEntries(Object.entries(reliability.direction || {}).map(
      ([direction, bins]) => [direction, populated(bins)],
    )),
    thresholds: Object.fromEntries((reliability.thresholds || []).map((item) => {
      const sign = item.threshold > 0 ? "+" : "";
      return [`${item.operator}_${sign}${item.threshold}_percent`, populated(item.bins)];
    })),
  };
}

function compactEvaluationScores(scores) {
  if (!scores) return null;
  const { name, version, definition, direction_brier, reliability } = scores;
  return {
    name, version, definition,
    direction_Brier: direction_brier,
    threshold_Brier: (scores.threshold_brier || []).map((item) => `${item.operator} ${item.threshold > 0 ? "+" : ""}${item.threshold}%: ${formatNumber(item.score)}`),
    reliability: compactReliability(reliability),
    interval_coverage: (scores.interval_coverage || []).map((item) => `${formatPercent(item.level)}: ${item.covered_count}/${item.sample_count}, ${formatPercent(item.coverage)}; ${item.definition}`),
  };
}

function compactEvaluation(evaluation) {
  if (!evaluation) return null;
  return { ...evaluation, forecast_model: compactEvaluationScores(evaluation.forecast_model), baseline: compactEvaluationScores(evaluation.baseline) };
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
  } catch (error) {
    if (error.name === "AbortError") throw error;
    body = { error: { code: "invalid_response", message: "The local service returned an invalid response." } };
  }
  if (!response.ok) {
    const error = new Error(body.error?.message || body.detail || "Local service request failed.");
    error.code = body.error?.code || "request_failed";
    error.requestId = body.error?.request_id || "";
    error.status = response.status;
    throw error;
  }
  return body;
}

function tableRow(table, label, value) {
  const row = table.insertRow();
  const heading = element("th");
  heading.scope = "row";
  heading.textContent = label;
  row.append(heading, element("td", "", value));
  return row;
}

function appendMeta(meta, fields) {
  for (const [label, value] of fields) {
    if (value === null || value === undefined || value === "") continue;
    const cell = element("div");
    cell.append(element("span", "data-label", label), element("strong", "", value));
    meta.append(cell);
  }
}

function inputLimitations(input) {
  return [...input.limitations, input.provider_metadata.intraday_archive_limit.statement];
}

function directionValue(probabilities, direction) {
  if (direction === "flat") return probabilities.flat ?? probabilities.unchanged ?? 0;
  return probabilities[direction] ?? 0;
}

function renderTailChart(result, chartId) {
  const figure = element("figure", "tail-figure");
  const caption = element("figcaption", "", "Threshold tail profile");
  const captionId = `${chartId}-caption`;
  caption.id = captionId;
  const svg = svgElement("svg", {
    class: "tail-chart",
    viewBox: "0 0 452 161",
    role: "img",
    "aria-labelledby": captionId,
  });
  const description = svgElement("desc");
  description.textContent = "Threshold probabilities: loss uses solid circles; gain uses dashed diamonds. Visible axes and details give exact values.";
  svg.append(description);

  const visual = element("div", "tail-chart-visual");
  const yTitle = element("span", "chart-axis-label chart-y-title", "PROBABILITY");
  const yTicks = element("div", "chart-y-ticks");
  for (const probability of [1, .5, 0]) {
    const label = element("span", "chart-axis-label chart-y-tick", formatPercent(probability));
    label.dataset.axisPosition = String(probability * 100);
    yTicks.append(label);
  }

  const x = (threshold) => (threshold + 10) * 22.6;
  const y = (probability) => 161 - Math.max(0, Math.min(1, probability)) * 161;
  for (const probability of [0, .5, 1]) {
    const rowY = y(probability);
    svg.append(svgElement("line", { class: "chart-grid", x1: 0, y1: rowY, x2: 452, y2: rowY }));
  }
  svg.append(
    svgElement("line", { class: "chart-axis", x1: 0, y1: 161, x2: 452, y2: 161 }),
    svgElement("line", { class: "chart-axis", x1: 0, y1: 0, x2: 0, y2: 161 }),
  );

  const thresholds = [...result.threshold_probabilities].sort((a, b) => a.threshold - b.threshold);
  const xTicks = element("div", "chart-x-ticks");
  for (const threshold of thresholds) {
    const label = element(
      "span",
      "chart-axis-label chart-x-tick",
      `${threshold.threshold > 0 ? "+" : ""}${threshold.threshold}%`,
    );
    label.dataset.axisPosition = String(threshold.threshold);
    xTicks.append(label);
  }
  const xTitle = element("span", "chart-axis-label chart-x-title", "RETURN THRESHOLD");

  const tooltipText = "Hover or focus a point for its probability.";
  const tooltip = element("p", "chart-tooltip", tooltipText);
  tooltip.setAttribute("aria-live", "polite");
  const resetTooltip = () => { tooltip.textContent = tooltipText; };
  for (const [kind, matcher] of [["loss", (item) => item.threshold < 0], ["gain", (item) => item.threshold > 0]]) {
    const points = thresholds.filter(matcher);
    const pointText = points.map((item) => `${x(item.threshold)},${y(item.probability)}`).join(" ");
    svg.append(svgElement("polyline", { class: `chart-line ${kind}`, points: pointText }));
    for (const item of points) {
      const operator = kind === "loss" ? "at or below" : "at or above";
      const signed = `${item.threshold > 0 ? "+" : ""}${item.threshold}%`;
      const accessible = `${formatPercent(item.probability)} probability of return ${operator} ${signed}`;
      const point = kind === "loss"
        ? svgElement("circle", { class: `chart-point ${kind}`, cx: x(item.threshold), cy: y(item.probability), r: 6 })
        : svgElement("rect", {
          class: `chart-point ${kind}`,
          x: x(item.threshold) - 5,
          y: y(item.probability) - 5,
          width: 10,
          height: 10,
          transform: `rotate(45 ${x(item.threshold)} ${y(item.probability)})`,
        });
      const rowId = `${chartId}-threshold-${kind}-${Math.abs(item.threshold)}`;
      point.setAttribute("tabindex", "0");
      point.setAttribute("role", "img");
      point.setAttribute("aria-label", accessible);
      point.setAttribute("aria-controls", rowId);
      const title = svgElement("title");
      title.textContent = accessible;
      point.append(title);
      for (const event of ["focus", "mouseenter"]) {
        point.addEventListener(event, () => { tooltip.textContent = accessible; });
      }
      for (const event of ["blur", "mouseleave"]) point.addEventListener(event, resetTooltip);
      point.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        const row = document.getElementById(rowId);
        row.closest("details").open = true;
        row.focus();
      });
      svg.append(point);
    }
  }

  const legend = element("div", "chart-legend");
  const lossLegend = element("span");
  lossLegend.append(element("i", "legend-mark"), document.createTextNode("Loss tail · at or below · solid circles"));
  const gainLegend = element("span");
  gainLegend.append(element("i", "legend-mark gain"), document.createTextNode("Gain tail · at or above · dashed diamonds"));
  legend.append(lossLegend, gainLegend);
  visual.append(yTitle, yTicks, svg, xTicks, xTitle);
  figure.append(caption, visual, legend, tooltip);
  return figure;
}

function renderHorizonComparison(results) {
  const section = element("section", "horizon-comparison");
  section.setAttribute("aria-labelledby", "horizon-scan-heading");
  const title = element("header", "comparison-title");
  const heading = element("h3", "", "Horizon scan");
  heading.id = "horizon-scan-heading";
  title.append(heading, element("p", "", "Shared target · different completed origins"));
  const rows = element("div", "comparison-rows");
  for (const result of results) {
    const row = element("article", "comparison-row");
    const rowTitle = element("h4", "", result.horizon === "close_to_close" ? "Daily close origin" : "Five-minute origin");
    rowTitle.append(element("span", "", result.horizon === "close_to_close" ? "Daily origin" : "Intraday origin"));
    row.append(rowTitle);
    for (const [direction, label] of [["down", "Down"], ["flat", "Unchanged"], ["up", "Up"]]) {
      const stat = element("div", `comparison-stat ${direction}`);
      stat.append(element("strong", "", formatPercent(directionValue(result.direction_probabilities, direction))), element("small", "", label));
      row.append(stat);
    }
    rows.append(row);
  }
  section.append(title, rows);
  return section;
}

function identityValue(identity, key) {
  const value = identity?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function hideOptions() {
  activeOption = -1;
  optionsBox.hidden = true;
  optionsBox.replaceChildren();
  symbolInput.setAttribute("aria-expanded", "false");
  symbolInput.removeAttribute("aria-activedescendant");
}

function clearIdentity() {
  selectedIdentity = null;
  identityBox.hidden = true;
  identityBox.replaceChildren();
}

function setNewsState(content, state, message) {
  content.dataset.state = state;
  content.setAttribute("aria-busy", String(state === "loading"));
  const status = element("p", "news-status", message);
  status.setAttribute("role", "status");
  content.replaceChildren(status);
}

function setNewsRetryState(content, state, message, symbol, limit) {
  setNewsState(content, state, message);
  const retry = element("button", "secondary news-retry", "Retry headlines");
  retry.type = "button";
  retry.addEventListener("click", () => {
    retry.disabled = true;
    loadNews(content, symbol, limit);
    content.focus();
  });
  content.append(retry);
}

function supersedeNews() {
  if (!newsRequest) return;
  newsRequest.abort();
  newsRequest = null;
  const content = resultContent.querySelector(".news-content");
  if (content) setNewsState(content, "superseded", "Headline request superseded because the instrument changed.");
}

function safeNewsLink(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed.href : null;
  } catch (_) {
    return null;
  }
}

function renderNews(content, data, symbol, limit) {
  const items = data.items.slice(0, limit);
  const stale = data.cache_state === "stale_fallback";
  const partial = data.coverage.partial_metadata;
  setNewsState(
    content,
    !items.length ? "empty" : stale ? "stale" : partial ? "partial" : "fresh",
    !items.length
      ? `No current headlines were returned for ${symbol}.`
      : stale
      ? "Showing stale cached headlines because the provider refresh failed."
      : partial
        ? "Current headlines loaded with partial source or publication metadata."
        : "Current headlines loaded.",
  );
  content.append(element("p", "news-meta", `Source: ${data.provider} · As of: ${formatTime(data.as_of)}`));
  if (!items.length) return;
  const list = element("ol", "news-list");
  for (const item of items) {
    const row = element("li");
    const heading = element("h3");
    const href = safeNewsLink(item.url);
    if (href) {
      const link = element("a", "news-link", item.title);
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      heading.append(link, element("span", "external-warning", " External site ↗"));
    } else {
      heading.append(document.createTextNode(item.title), element("span", "external-warning", " Link unavailable"));
    }
    row.append(heading);
    const metadata = [item.publisher, item.published_at && formatTime(item.published_at)].filter(Boolean);
    if (metadata.length) row.append(element("p", "news-meta", metadata.join(" · ")));
    list.append(row);
  }
  content.append(list);
  if (limit === 5 && items.length === 5) {
    const more = element("button", "secondary news-more", "Show up to 10 headlines");
    more.type = "button";
    more.addEventListener("click", () => { loadNews(content, symbol, 10); content.focus(); });
    content.append(more);
  }
}

async function loadNews(content, symbol, limit = 5) {
  supersedeNews();
  const controller = new AbortController();
  let timedOut = false;
  newsRequest = controller;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, newsTimeoutMs);
  setNewsState(content, "loading", `Loading current headlines for ${symbol}…`);
  const retry = (state, message) => setNewsRetryState(content, state, message, symbol, limit);
  try {
    const data = await api(`/news?${new URLSearchParams({ symbol, limit: String(limit) })}`, {
      signal: controller.signal,
    });
    if (newsRequest !== controller) return;
    renderNews(content, data, symbol, limit);
  } catch (error) {
    if (newsRequest !== controller) return;
    if (error.name === "AbortError" && timedOut) {
      retry("unreachable", "The headline request timed out. Check the local service and try again.");
    } else if (error.name === "AbortError") return;
    else if (error.status === 503) retry("busy", "Headline capacity is busy. Try again shortly.");
    else if (error.status === 502) retry("unavailable", "The headline provider is unavailable and no cached headlines exist.");
    else if (error instanceof TypeError) retry("unreachable", "The local service is unreachable. Start it and try again.");
    else retry("unavailable", error.message);
  } finally {
    clearTimeout(timeout);
    if (newsRequest === controller) newsRequest = null;
  }
}

function newsDisclosure(input, context) {
  const symbol = input.canonical_symbol || input.symbol;
  const details = element("details", "news-panel");
  const summary = element(
    "summary",
    "",
    context === "saved" ? "Load current headlines for this symbol" : "Current headlines for this symbol",
  );
  const content = element("div", "news-content");
  content.tabIndex = -1;
  content.setAttribute("aria-live", "polite");
  setNewsState(content, "not-requested", "Headlines not requested.");
  details.append(
    summary,
    element("p", "news-separation", "Current headlines are live, not forecast or ledger evidence."),
    content,
  );
  details.addEventListener("toggle", () => {
    if (details.open && !details.dataset.requested) {
      details.dataset.requested = "true";
      loadNews(content, symbol);
    }
  });
  return details;
}

function confirmIdentity(identity) {
  const value = (key) => identityValue(identity, key);
  const symbol = value("canonical_symbol");
  if (!symbol) return;
  selectedIdentity = identity;
  symbolInput.value = symbol;
  symbolError.textContent = "";
  symbolInput.removeAttribute("aria-invalid");
  const assetControl = forecastForm.querySelector(
    `input[name="asset_type"][value="${identity.asset_type}"]`,
  );
  if (assetControl) assetControl.checked = true;
  const title = value("display_name") || value("company_name");
  const details = [
    symbol,
    value("exchange"),
    value("currency"),
    value("timezone"),
    value("asset_type")?.toUpperCase(),
  ].filter(Boolean).join(" / ");
  identityBox.replaceChildren(
    element("strong", "", title || symbol),
    element("span", "", ` Confirmed identity: ${details}`),
  );
  identityBox.hidden = false;
  lookupStatus.textContent = `Selected ${title || symbol}.`;
  hideOptions();
}

function setActiveOption(index) {
  const options = [...optionsBox.querySelectorAll("[role=option]")];
  if (!options.length) return;
  activeOption = Math.max(0, Math.min(index, options.length - 1));
  options.forEach((option, optionIndex) => {
    option.setAttribute("aria-selected", String(optionIndex === activeOption));
  });
  symbolInput.setAttribute("aria-activedescendant", options[activeOption].id);
  options[activeOption].scrollIntoView({ block: "nearest" });
}

function renderInstrumentOptions(items, query) {
  optionsBox.replaceChildren();
  activeOption = -1;
  if (!items.length) {
    hideOptions();
    lookupStatus.textContent = `No identity matches “${query}”; a valid typed symbol can still be submitted.`;
    return;
  }
  items.forEach((identity, index) => {
    const value = (key) => identityValue(identity, key);
    const option = element("li", "instrument-option");
    option.id = `instrument-option-${lookupSequence}-${index}`;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", "false");
    const name = value("display_name") || value("company_name");
    const facts = [
      value("canonical_symbol"),
      value("exchange"),
      value("currency"),
      value("asset_type")?.toUpperCase(),
    ].filter(Boolean).join(" / ");
    option.append(element("strong", "", name || identity.canonical_symbol), element("span", "", facts));
    option.addEventListener("mousedown", (event) => event.preventDefault());
    option.addEventListener("click", () => confirmIdentity(identity));
    optionsBox.append(option);
  });
  optionsBox.hidden = false;
  symbolInput.setAttribute("aria-expanded", "true");
  lookupStatus.textContent = `${items.length} bounded identity ${items.length === 1 ? "match" : "matches"}. Use arrow keys and Enter to select.`;
}

async function lookupInstruments(query) {
  lookupSequence += 1;
  const sequence = lookupSequence;
  if (lookupRequest) lookupRequest.abort();
  const controller = new AbortController();
  lookupRequest = controller;
  lookupStatus.textContent = `Looking up “${query}”…`;
  try {
    const data = await api(`/instruments?${new URLSearchParams({ query, limit: "5" })}`, {
      signal: controller.signal,
    });
    if (sequence !== lookupSequence || symbolInput.value.trim() !== query) return null;
    renderInstrumentOptions(data.items.slice(0, 5), query);
    return data.items.slice(0, 5);
  } catch (error) {
    if (error.name === "AbortError" || sequence !== lookupSequence) return null;
    hideOptions();
    lookupStatus.textContent = `Identity lookup unavailable: ${error.message}`;
    return null;
  } finally {
    if (lookupRequest === controller) lookupRequest = null;
  }
}

function cancelPendingLookup() {
  clearTimeout(lookupTimer);
  lookupTimer = null;
  lookupSequence += 1;
  if (lookupRequest) lookupRequest.abort();
  lookupRequest = null;
}

symbolInput.addEventListener("input", () => {
  supersedeNews();
  cancelPendingLookup();
  clearIdentity();
  hideOptions();
  const query = symbolInput.value.trim();
  if (query.length < 2) {
    lookupStatus.textContent = "";
    return;
  }
  // Delay symbol lookup so immediate submission can supersede it.
  const delay = /^[A-Z0-9.^-]{1,15}$/.test(query) ? 1200 : 300;
  lookupTimer = setTimeout(() => lookupInstruments(query), delay);
});

symbolInput.addEventListener("keydown", (event) => {
  const options = [...optionsBox.querySelectorAll("[role=option]")];
  if (optionsBox.hidden || !options.length) return;
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
  const chartId = `tail-chart-${result.horizon}-${chartSequence += 1}`;
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
  chart.setAttribute("aria-label", `Down ${formatPercent(directionValue(probabilities, "down"))}, unchanged ${formatPercent(directionValue(probabilities, "flat"))}, up ${formatPercent(directionValue(probabilities, "up"))}`);
  for (const direction of ["down", "flat", "up"]) {
    const bar = element("div", `probability-bar ${direction}`);
    const fill = element("meter", "fill");
    fill.min = 0;
    fill.max = 1;
    const probability = directionValue(probabilities, direction);
    fill.value = probability;
    fill.textContent = formatPercent(probability);
    const directionLabel = direction === "flat" ? "unchanged" : direction;
    bar.append(element("span", "value", formatPercent(probability)), fill, element("span", "label", directionLabel));
    chart.append(bar);
  }
  card.append(chart, renderTailChart(result, chartId));

  const contextTable = element("table", "details-table context-table");
  contextTable.append(element("caption", "", "Origin and target context"));
  const contextBody = element("tbody");
  contextTable.append(contextBody);
  for (const [label, value] of [
    ["Origin price", formatPrice(result.origin_price, input.currency)],
    ["Origin timestamp", formatTime(result.origin_timestamp)],
    ["Reference timestamp", formatTime(result.reference_timestamp || result.origin_timestamp)],
    ["Reference state", contractLabel(result.reference_state || "reported_origin")],
    ["Target close", formatTime(result.target_timestamp)],
    ["Target state", contractLabel(result.target_state || "scheduled_session_close")],
    ["Session at request", contractLabel(result.session_state_at_request || input.session_state_at_request)],
    ["Session semantics", result.target_session_rule || input.session_rule],
    ["Calculated at", formatTime(result.calculated_at)],
  ]) tableRow(contextBody, label, value);
  if (result.origin_bar_end) {
    tableRow(
      contextBody,
      "Completed-bar evidence",
      `Five-minute bar ended ${formatTime(result.origin_bar_end)} by cutoff ${formatTime(input.request_cutoff)}; an active incomplete bar is excluded.`,
    );
  }
  card.append(contextTable);

  const table = element("table", "details-table");
  table.append(element("caption", "", "Direction and threshold details"));
  const body = element("tbody");
  table.append(body);
  const definitions = probabilities.definitions || {};
  tableRow(body, "Down probability", `${formatPercent(probabilities.down)} · ${definitions.down || "return below the flat range"}`);
  tableRow(body, "Unchanged probability", `${formatPercent(directionValue(probabilities, "flat"))} · ${definitions.flat || definitions.unchanged || probabilities.flat_definition}`);
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
    const row = tableRow(body, `Return ${operator} ${signedThreshold}`, details);
    row.id = `${chartId}-threshold-${threshold.threshold < 0 ? "loss" : "gain"}-${Math.abs(threshold.threshold)}`;
    row.tabIndex = -1;
  }
  const conditional = contractSection(
    "Conditional gain / loss magnitudes",
    "conditional-details",
    result.conditional_magnitudes || result.conditional_probabilities || result.conditional_gain_loss,
  );

  const intervalTable = element("table", "details-table interval-table");
  intervalTable.append(element("caption", "", "Return and price intervals"));
  const intervalBody = element("tbody");
  intervalTable.append(intervalBody);
  for (const interval of result.magnitude_intervals) {
    tableRow(
      intervalBody,
      `${formatPercent(interval.level)} magnitude interval (return and price)`,
      `${interval.definition}: ${interval.percent.low.toFixed(2)}% to ${interval.percent.high.toFixed(2)} percent return (${interval.percent.unit}); ${formatPrice(interval.price.low, input.currency)} to ${formatPrice(interval.price.high, input.currency)} (${interval.price.unit})`,
    );
  }
  card.append(intervalTable);

  for (const [label, value] of [
    ["Model", `${result.model?.name || input.model.name} / ${result.model?.version || result.model_version || input.model.version}`],
    ["Forecast contract", result.forecast_contract_version || input.forecast_contract_version],
    ["Model fingerprint", result.model_fingerprint || input.model_fingerprint],
    ["Forecast fingerprint", result.forecast_fingerprint],
    ["Historical sample count", String(result.sample_size)],
    ["Distribution", result.distribution_definition],
  ]) tableRow(body, label, value);

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
  const evaluation = contractSection(
    "Chronological walk-forward evaluation",
    "evaluation-details",
    compactEvaluation(
      result.evaluation || input.evaluations?.[result.horizon] || input.evaluation?.[result.horizon],
    ),
  );
  card.append(disclosure("Threshold, uncertainty, and evaluation details", "forecast-forensics",
    table, ...[conditional, uncertainty, evaluation].filter(Boolean)));

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
  supersedeNews();
  const input = data.input;
  showContent(resultContent, "", false);
  qualityBadge.className = `badge ${context === "saved" ? input.quality : data.repeated ? "repeated" : input.quality}`;
  qualityBadge.textContent = context === "saved"
    ? `Recorded quality: ${input.quality}`
    : data.repeated ? `Repeated / ${input.quality}` : input.quality;

  const stateStrip = element(
    "p",
    "state-strip",
    context === "saved"
      ? `Immutable recorded result · audit event #${data.event.id}. Forecast inputs and values are reopened exactly as saved; append-only outcomes remain separate.`
      : data.repeated
        ? `Repeated request recorded as audit event #${data.event.id}; ${data.reused ? "the identical saved forecast was reused." : "new provider input created a new immutable run."}`
        : `Successful request recorded as audit event #${data.event.id}.`,
  );
  resultContent.append(stateStrip);
  const qualityReasons = input.quality_reasons || input.stale_state?.reasons || [];
  if (input.quality === "stale") {
    const summary = element("p", "quality-summary", `Stale-data reason: ${qualityReasons.join("; ") || "No reason reported"}. `);
    const link = element("a", "text-link", "Review detailed provenance");
    link.href = "#forecast-provenance";
    link.addEventListener("click", () => { document.getElementById(link.hash.slice(1)).open = true; });
    summary.append(link);
    resultContent.append(summary);
  }

  const fields = [
    ["Display name", input.display_name],
    ["Company name", input.company_name],
    ["Canonical symbol", `${input.canonical_symbol || input.symbol} · recorded identity`],
    ["Instrument type", `${[input.asset_type?.toUpperCase(), input.quote_type].filter(Boolean).join(" / ")} · recorded type`],
    ["Exchange", input.exchange],
    ["Currency", input.currency],
    ["Exchange timezone", input.exchange_timezone],
    ["Provider as-of", formatTime(input.provider_as_of)],
    ["Calculated", formatTime(input.captured_at)],
    ["Source", input.provider],
    ["Model", `${input.model.name} / ${input.model.version}`],
  ];
  const meta = element("div", "forecast-meta");
  appendMeta(meta, [
    ["Instrument", input.canonical_symbol || input.symbol],
    ["Name", input.display_name || input.company_name],
    ["Instrument type", [input.asset_type?.toUpperCase(), input.quote_type].filter(Boolean).join(" / ")],
    ["Context", `${[input.exchange, input.currency].filter(Boolean).join(" / ")} · ${input.provider} · as of ${formatTime(input.provider_as_of)}`],
  ]);
  const calculationDetails = element("div", "calculation-details");
  appendMeta(calculationDetails, fields);
  meta.append(disclosure("Instrument and calculation details", "instrument-details", calculationDetails));
  resultContent.append(meta);
  resultContent.append(newsDisclosure(input, context));
  resultContent.append(renderHorizonComparison(data.results));
  const grid = element("div", "forecast-grid");
  for (const result of data.results) grid.append(renderForecastCard(result, input));
  resultContent.append(grid);
  const limitations = inputLimitations(input);
  const missing = Object.fromEntries(
    Object.entries(input.provider_metadata || {}).filter(([key]) => key.includes("missing")),
  );
  const provenance = disclosure(`Data quality · Provider: ${input.provider}. Response as-of: ${formatTime(input.provider_as_of)}. Stale state: ${input.stale_state?.state || input.quality}. ${(input.quality_reasons || input.stale_state?.reasons || []).join("; ") || "No stale-data reasons."}`,
    "provenance provider-provenance");
  provenance.id = "forecast-provenance";
  for (const text of [
    `Session at request: ${contractLabel(input.session_state_at_request)}. Session rule: ${input.session_rule}`,
    `Calendar: ${input.calendar.name} / ${input.calendar.version} / ${input.calendar.timezone}.`,
    `Captured prices: ${input.selected_daily_bars.length} daily closes and ${input.selected_intraday_bars.length} completed intraday bars.`,
    `Missing data: ${Object.keys(missing).length ? "provider missing-data counters follow." : "no missing bars or scheduled closes reported."}`,
    `Limitations, including archive availability: ${limitations.join(" ") || "No provider limitations reported."}`,
    `Content fingerprint: ${input.content_fingerprint}`,
    context === "saved"
      ? `Audit event #${data.event.id} references immutable forecast run #${data.event.run_id}.`
      : `Audit event #${data.event.id}${data.reused ? " references an identical immutable forecast run." : " records a new immutable forecast run."}`,
  ]) provenance.append(element("p", "", text));
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

function errorPanel(title, error, context) {
  const panel = element("div", "error-panel");
  panel.setAttribute("role", "alert");
  panel.append(
    element("h3", "", title),
    ...(context ? [element("p", "", context)] : []),
    element("p", "", error.message),
    element("p", "data-label", `Error code: ${error.code || "request_failed"}`),
  );
  if (error.requestId) panel.append(element("p", "data-label", `Audit request: ${error.requestId}`));
  return panel;
}

function renderError(error, title = "Forecast unavailable", context) {
  qualityBadge.className = "badge failed";
  qualityBadge.textContent = "Failed";
  showContent(resultContent, "", false, errorPanel(title, error, context));
}

function focusResultSection() {
  const section = $("#result-section");
  section.focus();
  section.scrollIntoView({ block: "start" });
}

forecastForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const typedQuery = symbolInput.value.trim();
  const symbol = typedQuery.toUpperCase();
  cancelPendingLookup();
  hideOptions();
  if (!/^[A-Z0-9.^-]{1,15}$/.test(symbol)) {
    lookupStatus.textContent = "";
    const matches = typedQuery.length >= 2 ? await lookupInstruments(typedQuery) : null;
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
  const submit = $("#forecast-submit");
  selectionSequence += 1;
  submit.disabled = true;
  submit.querySelector("span").textContent = "Calculating…";
  qualityBadge.className = "badge neutral";
  qualityBadge.textContent = "Calculating";
  showContent(resultContent, "empty-state loading", true, element("p", "", `Retrieving completed bars for ${symbol}…`));
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
  const selection = selectionSequence += 1;
  supersedeNews();
  qualityBadge.className = "badge neutral";
  qualityBadge.textContent = "Loading saved event";
  showContent(resultContent, "empty-state loading", true, element("p", "",
    isFailure ? `Loading recorded failed request #${id}…` : `Loading saved forecast #${id}…`));
  announcement.textContent = `Loading saved audit event ${id}.`;
  try {
    const data = await api(isFailure ? `/history/${id}` : `/saved-forecasts/${id}`);
    if (selection !== selectionSequence) return;
    if (data.input) {
      data.repeated = data.event.status === "repeated";
      renderResult(data, "saved");
      focusResultSection();
      announcement.textContent = `Immutable recorded result ${id} reopened without recalculation.`;
    } else {
      const event = data.event;
      renderError(
        { code: event.error_code, message: `Saved error: ${event.error_message}`, requestId: event.request_id },
        "Recorded failed request",
        `Event #${event.id} · ${event.submitted_symbol} / ${event.asset_type.toUpperCase()} · ${formatTime(event.submitted_at)}. No forecast was saved.`,
      );
      qualityBadge.textContent = "Recorded failure";
      focusResultSection();
      announcement.textContent = `Recorded failed request ${id} loaded.`;
    }
  } catch (error) {
    if (selection !== selectionSequence) return;
    renderError(
      error,
      isFailure ? "Recorded failed request could not be retrieved" : "Saved forecast could not be retrieved",
      "Retrieval failed; no recorded data was replaced.",
    );
    qualityBadge.textContent = "Retrieval failed";
    announcement.textContent = `Saved event retrieval failed: ${error.message}`;
    focusResultSection();
  }
}

async function runFreshAnalysis(id) {
  if (freshInFlight) return;
  freshInFlight = true;
  document.querySelectorAll(".fresh-analysis-action").forEach((button) => { button.disabled = true; });
  let cutoff = null;
  // Keep fresh analysis separate from saved output.
  freshSection.hidden = false;
  showContent(
    freshContent,
    "empty-state loading",
    true,
    element("p", "", `Loading cutoff for source audit event #${id}…`),
  );
  announcement.textContent = `Fresh historical-cutoff analysis for event ${id} is running.`;
  freshSection.focus();
  try {
    const saved = await api(`/saved-forecasts/${id}`);
    cutoff = saved.input.request_cutoff;
    freshContent.replaceChildren(element(
      "p",
      "",
      `Calculating fresh analysis from source audit event #${id} at historical cutoff ${formatTime(cutoff)}…`,
    ));
    const response = await api(`/history/${id}/reconstructions`, {
      method: "POST",
      body: JSON.stringify({
        analysis_kind: "fresh_historical_reconstruction",
        cutoff,
      }),
    });
    const data = response.analysis || response;
    showContent(freshContent, "", false);
    cutoff = data.input?.request_cutoff || response.request_cutoff || cutoff;
    freshContent.append(element(
      "p",
      "state-strip",
      `Fresh analysis${data.event?.id ? ` recorded as new audit event #${data.event.id}` : ""} from source audit event #${id}${cutoff ? ` at historical cutoff ${formatTime(cutoff)}` : ""}. This is a new calculation and does not alter the immutable source forecast.`,
    ));
    if (!data.input || !data.results) throw new Error("Fresh analysis response omitted forecast details.");
    if (data.input.quality === "stale") freshContent.append(element(
      "p",
      "fresh-warning",
      `Stale reconstruction: ${data.input.quality_reasons.join("; ") || "No reason reported"}.`,
    ));
    const meta = element("div", "forecast-meta");
    appendMeta(meta, [
      ["Instrument", [data.input.canonical_symbol || data.input.symbol, data.input.display_name || data.input.company_name].filter(Boolean).join(" / ")],
      ["Source audit event", `#${id}`],
      ["Historical cutoff", formatTime(data.input.request_cutoff)],
      ["Provider", data.input.provider],
      ["Provider as-of", formatTime(data.input.provider_as_of)],
      ["Calculated", formatTime(data.input.captured_at)],
      ["Model", `${data.input.model.name} / ${data.input.model.version}`],
      ["Content fingerprint", data.input.content_fingerprint],
      ["Input quality", data.input.quality],
      ["Quality reasons", data.input.quality_reasons.join("; ") || "None reported"],
      ["Provider / archive limitations", inputLimitations(data.input).join(" ")],
    ]);
    freshContent.append(meta);
    const grid = element("div", "forecast-grid");
    for (const result of data.results) grid.append(renderForecastCard(result, data.input));
    freshContent.append(grid);
    announcement.textContent = `Fresh historical-cutoff analysis for event ${id} is ready in the separate analysis region.`;
  } catch (error) {
    showContent(
      freshContent,
      "",
      false,
      errorPanel(
        "Fresh analysis unavailable",
        error,
        `Source audit event #${id}${cutoff ? ` · historical cutoff ${formatTime(cutoff)}` : ""}.`,
      ),
    );
    announcement.textContent = `Fresh historical-cutoff analysis failed: ${error.message}`;
  } finally {
    freshInFlight = false;
    await loadHistory();
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
      // Rebuild relations only from bounded persisted history.
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
          relations.set(item.id, false);
        }
      }
    } catch (_) {
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

function instrumentHistoryCell(item) {
  const cell = element("td");
  const symbol = item.canonical_symbol || item.normalized_symbol || item.submitted_symbol || "Invalid";
  const company = item.display_name || item.company_name;
  cell.append(element("span", "request-label", symbol));
  if (company) cell.append(element("span", "run-label", company));
  return cell;
}

function evidenceHistoryCell(item) {
  const cell = element("td");
  const model = [item.model_name, item.model_version].filter(Boolean).join(" / ");
  cell.append(element("span", "request-label", model || "No completed model"));
  const horizons = Array.isArray(item.horizons) ? item.horizons : [];
  const evaluations = Array.isArray(item.evaluation_statuses)
    ? [...new Set(item.evaluation_statuses)].map(contractLabel).join(", ")
    : "";
  cell.append(element("span", "run-label", [
    horizons.length
      ? `${horizons.length} ${horizons.length === 1 ? "horizon" : "horizons"} (${horizons.map(contractLabel).join(", ")})`
      : "Horizon evidence unavailable",
    item.outcome_count === undefined ? "Outcome evidence unavailable" : `${item.outcome_count} outcomes`,
    evaluations ? `evaluation ${evaluations}` : "Evaluation evidence unavailable",
  ].join(" · ")));
  return cell;
}

function renderHistory(data, runRelations) {
  historyContent.setAttribute("aria-busy", "false");
  if (!data.items.length) {
    historyContent.replaceChildren(element("p", "empty-state", "No audit events match these filters."));
  } else {
    const table = element("table", "history-table");
    const caption = element("caption", "sr-only", "Submitted forecast search history");
    const head = element("thead");
    const headerRow = element("tr");
    for (const label of ["Request / run", "Instrument", "Type / venue", "Analysis", "Status", "Model / evidence", "Submitted", "Actions"]) {
      const heading = element("th", "", label);
      heading.scope = "col";
      headerRow.append(heading);
    }
    head.append(headerRow);
    const body = element("tbody");
    for (const item of data.items) {
      const row = element("tr");
      const requestCell = element("td");
      const runLabel = element("span", "run-label", runDisposition(item, runRelations));
      requestCell.append(
        element("span", "request-label", `New request #${item.id}`),
        runLabel,
      );
      const cells = [
        ["Request / run", requestCell],
        ["Instrument", instrumentHistoryCell(item)],
        ["Type / venue", element("td", "", [item.asset_type.toUpperCase(), item.exchange].filter(Boolean).join(" / "))],
        ["Analysis", element("td", "", analysisLabel(item))],
        ["Status", element("td", `status-${item.status}`, item.status)],
        ["Model / evidence", evidenceHistoryCell(item)],
        ["Submitted", element("td", "", formatTime(item.submitted_at))],
      ];
      for (const [label, cell] of cells) {
        cell.dataset.label = label;
        row.append(cell);
      }
      const actionCell = element("td");
      actionCell.className = "history-actions";
      actionCell.dataset.label = "Actions";
      const action = element("button", "", item.status === "failed" ? "View failed request" : "Reopen saved forecast");
      action.type = "button";
      action.addEventListener("click", () => showHistoryEvent(item.id, item.status === "failed"));
      actionCell.append(action);
      if (item.status !== "failed") {
        const fresh = element("button", "fresh-analysis-action", "Run fresh cutoff analysis");
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
  historyPage = data.page;
  lastPage = Math.max(1, Math.ceil(data.total / data.page_size));
  $("#history-page").textContent = `Page ${data.page} of ${lastPage}`;
  historyPrevious.disabled = data.page <= 1;
  historyNext.disabled = data.page * data.page_size >= data.total;
}

async function loadHistory() {
  const sequence = historySequence += 1;
  historyPrevious.disabled = true;
  historyNext.disabled = true;
  const values = new FormData(historyForm);
  const pageSize = ["10", "20", "50"].includes(values.get("page_size"))
    ? values.get("page_size")
    : "10";
  const params = new URLSearchParams({ page: String(historyPage), page_size: pageSize });
  for (const name of ["q", "status", "asset_type", "analysis_kind", "model", "horizon"]) {
    if (values.get(name)) params.set(name, values.get(name));
  }
  if (values.get("submitted_from")) params.set("submitted_from", `${values.get("submitted_from")}T00:00:00Z`);
  if (values.get("submitted_to")) params.set("submitted_to", `${values.get("submitted_to")}T23:59:59.999Z`);
  const [sortBy, sortOrder] = String(values.get("sort") || "event_id:desc").split(":");
  params.set("sort_by", sortBy);
  params.set("sort_order", sortOrder);
  const exportParams = new URLSearchParams(params);
  exportParams.delete("page");
  exportParams.delete("page_size");
  historyContent.setAttribute("aria-busy", "true");
  historyContent.replaceChildren(element("p", "history-loading", "Loading bounded audit history…"));
  try {
    const data = await api(`/history?${params}`);
    if (sequence !== historySequence) return;
    const relations = await persistedRunRelations(data.items);
    if (sequence !== historySequence) return;
    $("#export-csv").href = `${apiRoot}/history-export.csv?${exportParams}`;
    $("#export-json").href = `${apiRoot}/history-export.json?${exportParams}`;
    renderHistory(data, relations);
  } catch (error) {
    if (sequence !== historySequence) return;
    historyContent.setAttribute("aria-busy", "false");
    const panel = element("p", "error-panel", `History unavailable: ${error.message}`);
    panel.setAttribute("role", "alert");
    historyContent.replaceChildren(panel);
    $("#history-page").textContent = "Page unavailable";
  }
}

historyForm.addEventListener("submit", (event) => {
  event.preventDefault();
  historyPage = 1;
  loadHistory();
});
historyPrevious.addEventListener("click", () => {
  if (historyPage <= 1) return;
  historyPage -= 1;
  loadHistory();
});
historyNext.addEventListener("click", () => {
  if (historyPage >= lastPage) return;
  historyPage += 1;
  loadHistory();
});

async function initialize() {
  const state = $(".system-state");
  try {
    const [readiness, backup] = await Promise.all([api("/readiness"), api("/operations/backups/status")]);
    state.classList.add("ready");
    $("#system-label").textContent = `Local service ready / ${readiness.provider} / backup ${backup.status}`;
  } catch (_) {
    state.classList.add("failed");
    $("#system-label").textContent = "Local service unavailable";
  }
  await loadHistory();
}

initialize();
