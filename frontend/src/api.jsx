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

// Sources could once be added and removed from here, when they were rows
// in a table read by a generic engine. They are written in code now — the
// sites differ too much to be read any other way — so the list is fixed
// and Update is the only thing this page can ask for.

// Runs the scraper for one source now, instead of waiting for the daily
// timer, and returns what it did. A full crawl, so this source's events
// end up right — which at one polite request per second can take minutes
// on a large site.
export function updateSource(name) {
  return sendJSON('/api/sources/update', 'POST', { name })
}

// What one source has actually put in the database — the list behind the
// events/places pill. A count says a source is working; only the rows say
// whether what it produced is any good.
export function fetchContribution(name) {
  return getJSON(`/api/sources/contribution?name=${encodeURIComponent(name)}`)
}
