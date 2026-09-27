export type AssetType = "stock" | "etf";

export interface SelectedInstrument {
  provider: string;
  canonicalSymbol: string;
  assetType: AssetType;
  exchange: string;
  displayName: string;
}

const identityParameters = ["symbol", "asset_type", "exchange", "provider", "display_name"];
export const instrumentChangeEvent = "workspace-instrument-change";

function boundedValue(parameters: URLSearchParams, name: string, maximum: number) {
  const value = parameters.get(name)?.trim();
  return value && value.length <= maximum ? value : null;
}

export function instrumentFromSearch(search: string): SelectedInstrument | null {
  const parameters = new URLSearchParams(search);
  const symbol = boundedValue(parameters, "symbol", 80);
  const assetType = boundedValue(parameters, "asset_type", 8);
  const exchange = boundedValue(parameters, "exchange", 40);
  if (!symbol || (assetType !== "stock" && assetType !== "etf") || !exchange) return null;

  return {
    provider: boundedValue(parameters, "provider", 80) ?? "yahoo",
    canonicalSymbol: symbol.toUpperCase(),
    assetType,
    exchange: exchange.toUpperCase(),
    displayName: boundedValue(parameters, "display_name", 200) ?? symbol.toUpperCase(),
  };
}

export function instrumentHref(path: string, instrument: SelectedInstrument | null) {
  if (!path.startsWith("/") || path.startsWith("//")) throw new TypeError("workspace paths must be local");

  const target = new URL(path, "https://workspace.invalid");
  for (const name of identityParameters) target.searchParams.delete(name);
  if (instrument) {
    target.searchParams.set("symbol", instrument.canonicalSymbol);
    target.searchParams.set("asset_type", instrument.assetType);
    target.searchParams.set("exchange", instrument.exchange);
    target.searchParams.set("provider", instrument.provider);
    target.searchParams.set("display_name", instrument.displayName);
  }
  return `${target.pathname}${target.search}${target.hash}`;
}

export function replaceInstrumentInUrl(instrument: SelectedInstrument) {
  const path = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.history.replaceState(window.history.state, "", instrumentHref(path, instrument));
  window.dispatchEvent(new Event(instrumentChangeEvent));
}
