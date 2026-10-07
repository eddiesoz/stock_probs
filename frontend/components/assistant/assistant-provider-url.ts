// Endpoint form checks hide embedded credentials/query data; server egress policy still owns resolution.
export function providerBaseUrlIsSecure(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.hash && !url.search;
  } catch {
    return false;
  }
}

export function safeConfiguredBaseUrl(value: unknown): string {
  if (typeof value !== "string" || value.length > 2048) return "";
  return providerBaseUrlIsSecure(value) ? value : "";
}
