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
