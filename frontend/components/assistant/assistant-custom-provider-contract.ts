export type CustomProviderReview = {
  terms_url: string;
  privacy_disclosure: string;
  billing_disclosure: string;
  billing_class: "unknown" | "free" | "paid";
  endpoint_policy_reviewed: boolean;
};

// Reject obvious local names here; the server resolver remains the boundary against private addresses.
const localHostSuffixes = [".localhost", ".local", ".localdomain", ".internal", ".lan", ".home.arpa", ".test", ".invalid", ".example", ".onion"];

function isPublicHttpsUrl(value: string): boolean {
  if (!value || value.length > 2048 || value !== value.trim() || /[\u0000-\u0020\u007f\\]/.test(value)) return false;
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    const ipv4 = /^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname);
    const local = hostname === "localhost" || localHostSuffixes.some((suffix) => hostname.endsWith(suffix));
    const portAllowed = !url.port || url.port === "443";
    return url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash
      && portAllowed && !ipv4 && !hostname.startsWith("[") && !local && hostname.includes(".");
  } catch {
    return false;
  }
}

function disclosureIsBounded(value: string): boolean {
  if (value !== value.trim() || !value.trim()) return false;
  const bytes = new TextEncoder().encode(value).byteLength;
  if (bytes < 1 || bytes > 2000) return false;
  for (const character of value) {
    const code = character.codePointAt(0) ?? 0;
    if ((code < 0x20 && ![0x09, 0x0a, 0x0d].includes(code)) || (code >= 0x7f && code <= 0x9f)) return false;
  }
  return true;
}

export function customProviderReviewIsValid(baseUrl: string, review: CustomProviderReview): boolean {
  return Boolean(
    isPublicHttpsUrl(baseUrl)
    && isPublicHttpsUrl(review.terms_url)
    && disclosureIsBounded(review.privacy_disclosure)
    && disclosureIsBounded(review.billing_disclosure)
    && ["unknown", "free", "paid"].includes(review.billing_class)
    && review.endpoint_policy_reviewed === true,
  );
}

export function customProviderReviewTupleChanged(
  baseUrl: string,
  review: CustomProviderReview,
  saved: {
    selected_base_url?: string | null;
    selected_terms_url?: string | null;
    selected_privacy_disclosure?: string | null;
    selected_billing_disclosure?: string | null;
    selected_billing_class?: string | null;
  },
): boolean {
  return baseUrl.trim() !== (saved.selected_base_url ?? "")
    || review.terms_url.trim() !== (saved.selected_terms_url ?? "")
    || review.privacy_disclosure !== (saved.selected_privacy_disclosure ?? "")
    || review.billing_disclosure !== (saved.selected_billing_disclosure ?? "")
    || review.billing_class !== (saved.selected_billing_class ?? "unknown");
}
