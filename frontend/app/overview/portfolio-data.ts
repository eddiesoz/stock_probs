export interface PortfolioHolding {
  symbol: string;
  displayName: string;
  provider: string;
  assetType: "stock" | "etf";
  exchange: string;
  quantity: number | null;
}

// Defensive parsing: the UI trusts no response shape until it has been validated here.
function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? value as Record<string, unknown> : {};
}

// Quantity is nullable because older stored holdings may not record one; null is valid, but
// a negative or non-finite number is not.
function optionalNumber(value: unknown) {
  return value === null || (typeof value === "number" && Number.isFinite(value) && value >= 0);
}

// Returns null for any malformed item instead of a partial list: a strict all-or-nothing
// shape is what lets the workspace show an error rather than silently dropping holdings.
export function portfolioFromPayload(value: unknown): PortfolioHolding[] | null {
  const payload = record(value);
  if (payload.kind !== "portfolio" || !Array.isArray(payload.items)) return null;

  const items = payload.items.map((value): PortfolioHolding | null => {
    const item = record(value);
    if (
      typeof item.symbol !== "string" || !item.symbol
      || typeof item.display_name !== "string" || !item.display_name
      || typeof item.provider !== "string" || !item.provider
      || (item.asset_type !== "stock" && item.asset_type !== "etf")
      || typeof item.exchange !== "string" || !item.exchange
      || !optionalNumber(item.quantity)
    ) return null;
    return {
      symbol: item.symbol,
      displayName: item.display_name,
      provider: item.provider,
      assetType: item.asset_type,
      exchange: item.exchange,
      quantity: item.quantity as number | null,
    };
  });
  return items.every((item): item is PortfolioHolding => item !== null) ? items : null;
}

export function portfolioMutation(symbol: string, assetType: "stock" | "etf", quantity: string) {
  return {
    kind: "portfolio" as const,
    item: {
      symbol: symbol.trim().toUpperCase(),
      asset_type: assetType,
      quantity: Number(quantity),
    },
  };
}

// Allowed symbol characters mirror the backend's normalized symbol alphabet; quantity must
// be a positive finite number so a saved holding is never a zero or NaN position.
export function manualHoldingErrors(symbolValue: string, quantityValue: string) {
  const symbol = symbolValue.trim().toUpperCase();
  const allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^";
  const quantity = Number(quantityValue);
  return {
    symbol: !symbol || symbol.length > 15 || [...symbol].some((character) => !allowed.includes(character))
      ? "Enter 1–15 letters, numbers, periods, hyphens, or ^."
      : "",
    quantity: !quantityValue || !Number.isFinite(quantity) || quantity <= 0
      ? "Shares must be greater than zero."
      : "",
  };
}
