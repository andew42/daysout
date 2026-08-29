// User preferences, kept in localStorage — this is per-browser state and the
// server is stateless, so no server round-trip is needed.

const KEY = 'daysout-settings'

// Destination categories. Venues created from event listings carry the
// event's own category (craft, food, music, art) or 'venue' when the
// listing doesn't say.
export const ALL_CATEGORIES = [
  { id: 'historic-house', label: 'Historic houses' },
  { id: 'garden', label: 'Gardens' },
  { id: 'airfield', label: 'Airfields & aviation' },
  { id: 'art', label: 'Art' },
  { id: 'craft', label: 'Craft' },
  { id: 'food', label: 'Food & drink' },
  { id: 'music', label: 'Music' },
  { id: 'venue', label: 'Other venues' },
]

// Colour per category, shared by the map markers and the event list.
export const CATEGORY_COLORS = {
  'historic-house': '#8c4a2f',
  garden: '#2f6b4e',
  airfield: '#3a5da8',
  art: '#7b4397',
  craft: '#b5651d',
  food: '#a8323f',
  music: '#1f7a8c',
  venue: '#666666',
}

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
