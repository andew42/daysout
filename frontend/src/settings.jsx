// User preferences, kept in localStorage — this is per-browser state and the
// server is stateless, so no server round-trip is needed.

const KEY = 'daysout-settings'

export const ALL_CATEGORIES = [
  { id: 'historic-house', label: 'Historic houses' },
  { id: 'garden', label: 'Gardens' },
  { id: 'airfield', label: 'Airfields' },
]

const defaults = {
  postcode: '',
  minutes: 60,
  days: 7,
  categories: ALL_CATEGORIES.map(c => c.id),
}

export function loadSettings() {
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(KEY)) }
  } catch {
    return { ...defaults }
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings))
  } catch {
    // Private browsing etc. — settings just won't persist.
  }
}
