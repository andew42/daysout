// URLs reaching the UI were scraped from other people's pages, so they are
// untrusted text that happens to look like a link. Anything that is not
// plain http(s) — "javascript:" above all — must never reach an href.

export function webURL(url) {
  if (!url) return ''
  try {
    // No base: a scraped link is absolute or it is not a link. Resolving
    // "see our website" against our own origin would make it one.
    const parsed = new URL(url)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return ''
    return parsed.href
  } catch {
    return ''
  }
}
