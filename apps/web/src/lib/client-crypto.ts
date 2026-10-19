// LAN HTTP pages lack SubtleCrypto/randomUUID. getRandomValues remains available.
type BrowserCrypto = Partial<Pick<Crypto, "subtle" | "randomUUID" | "getRandomValues">>;

function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(
  bytes: ArrayBuffer,
  provider: BrowserCrypto | undefined = globalThis.crypto,
): Promise<string> {
  if (provider?.subtle) {
    return hex(new Uint8Array(await provider.subtle.digest("SHA-256", bytes)));
  }
  const { sha256 } = await import("@noble/hashes/sha2.js");
  return hex(sha256(new Uint8Array(bytes)));
}

export function submissionId(
  provider: BrowserCrypto | undefined = globalThis.crypto,
): string {
  if (provider?.randomUUID) return provider.randomUUID();
  if (!provider?.getRandomValues) {
    throw new Error("This browser cannot generate secure upload IDs. Use a current browser.");
  }
  const bytes = provider.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const value = hex(bytes);
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}
