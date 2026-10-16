// Financial calculations stay on the server; browser formatting never commits rounded amounts.
import { apiFetch } from "../auth-client";

export type Account = { id: string; label: string; account_type: string; revision: number; archived: number };
export type Cash = { account_id: string; currency: string; amount: string; display_value?: string | null; allocation_percent?: string | null };
export type Position = { account_id: string; symbol: string; asset_type: "stock" | "etf"; currency: string; quantity: string; book_cost: string | null; native_value?: string | null; display_value?: string | null; unrealized_display?: string | null; allocation_percent?: string | null; quote?: { price: string; provider: string; as_of: string; label: string } | null };
export type Realized = { transaction_id: string; account_id: string; symbol: string; currency: string; proceeds: string; allocated_cost: string | null; gain: string | null };
export type Book = { cash: Cash[]; positions: Position[]; realized: Realized[]; label: string };
export type BookState = { accounts: Account[]; book: Book; account_revisions: Record<string, number> };
export type Valuation = { complete: boolean; display_currency: "CAD" | "USD"; total_value: string | null; known_subtotal: string; cash_value: string | null; unrealized_gain: string | null; largest_position_percent: string | null; instrument_allocations: { symbol: string; asset_type: string; display_value: string; allocation_percent: string | null }[]; positions: Position[]; cash: Cash[]; realized: Realized[]; missing_inputs: { symbol: string; reason: string }[]; unknown_cost_count: number };
export type BaselineData = { captured_at: string; collection_completed_at: string; display_currency: "CAD" | "USD"; book: Book; accounts: Account[]; unavailable_quotes: { symbol: string; asset_type: string; reason: string }[]; quotes: { symbol: string; asset_type: "stock" | "etf"; currency: string; price: string; as_of: string; provider: string; label: string }[]; fx: Record<string, { value: string; publication_date?: string; provider: string }>; fx_status: { status: string; last_attempt_failed: boolean }; valuation: Valuation };
export type Baseline = { id: string; created_at: string; data: BaselineData };
export type Page<T> = { items: T[]; total: number; page: number; has_next: boolean };
export type Transaction = { id: string; account: string; effective_date: string; kind: string; currency: string; symbol: string | null; asset_type: "stock" | "etf"; quantity: string; price: string; amount: string; fee: string; book_cost: string | null; split_ratio: string; destination_account: string | null; destination_currency: string | null; received_amount: string; replaces: string | null; superseded?: boolean };
export type Preview = { preview_id: string; expires_at: string; transactions: Transaction[]; before: Book; after: Book; duplicate_ids: string[]; notice: string };
export type Assumptions = { price_shocks: { symbol: string; asset_type: "stock" | "etf"; percent: string }[]; usd_cad_percent: string; reallocations: { account_id: string; symbol: string; asset_type: "stock" | "etf"; amount: string; funding_currency: string }[] };
export type Simulation = { baseline_id: string; captured_at: string; before: Valuation; after: Valuation; value_difference: string | null; label: string; sequence: string; assumptions: Assumptions };
export type Scenario = { id: string; baseline_id: string; title: string; created_at: string; assumptions: Assumptions; result: Simulation };

export async function portfolioRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, { cache: "no-store", ...options });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.error?.message === "string" ? data.error.message : `Portfolio request failed (${response.status}).`);
  if (data === null || typeof data !== "object") throw new Error("The portfolio response is unavailable.");
  return data as T;
}
export const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export function money(value: string | null | undefined, currency = "CAD") { return value === null || value === undefined ? "Unavailable" : `${currency} ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
export function when(value: string) { return new Date(value).toLocaleString(); }
export function today() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; }
