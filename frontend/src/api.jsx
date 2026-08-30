// Thin fetch wrappers for the backend API.

async function getJSON(url) {
  const response = await fetch(url)
  const body = await response.json()
  if (!response.ok) {
    throw new Error(body.error || `${response.status} ${response.statusText}`)
  }
  return body
}

function query(settings, extra = {}) {
  const params = new URLSearchParams({
    postcode: settings.postcode,
    minutes: settings.minutes,
    categories: settings.categories.join(','),
    ...extra,
  })
  return params.toString()
}

export function fetchDestinations(settings) {
  return getJSON(`/api/destinations?${query(settings)}`)
}

export function fetchEvents(settings) {
  return getJSON(`/api/events?${query(settings, { days: settings.days })}`)
}

export function fetchGeocode(postcode) {
  return getJSON(`/api/geocode?postcode=${encodeURIComponent(postcode)}`)
}

export function fetchStatus() {
  return getJSON('/api/status')
}

async function sendJSON(url, method, body) {
  const response = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const result = await response.json()
  if (!response.ok) {
    throw new Error(result.error || `${response.status} ${response.statusText}`)
  }
  return result
}

export function fetchSources() {
  return getJSON('/api/sources')
}

// Adds a site for the scraper to visit on its next run. The server only
// records the row — nothing is fetched at this point, so a site that turns
// out to publish nothing usable is reported later, in its lastStatus.
export function addSource({ url, category, kind }) {
  return sendJSON('/api/sources', 'POST', { url, category, kind })
}

export function setSourceEnabled(name, enabled) {
  return sendJSON('/api/sources', 'PATCH', { name, enabled })
}

export function deleteSource(name) {
  return sendJSON(`/api/sources?name=${encodeURIComponent(name)}`, 'DELETE')
}
