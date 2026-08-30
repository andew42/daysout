import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchEvents } from './api.jsx'
import { CATEGORY_COLORS, loadSettings } from './settings.jsx'
import { webURL } from './links.jsx'

function formatDate(iso) {
  return new Date(iso + 'T12:00:00').toLocaleDateString('en-GB', {
    weekday: 'short', day: 'numeric', month: 'short',
  })
}

function dateRange(event) {
  if (event.startDate === event.endDate) return formatDate(event.startDate)
  return `${formatDate(event.startDate)} – ${formatDate(event.endDate)}`
}

export default function EventsView() {
  const [settings] = useState(loadSettings)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchEvents(settings).then(setResult).catch(e => setError(e.message))
  }, [settings])

  if (error) return <p className="notice error">{error}</p>
  if (!result) return <p className="notice">Loading…</p>

  // Standing programmes run for months and would otherwise bury the one-off
  // events you actually came to see, so they get their own section.
  const special = result.events.filter(event => !event.ongoing)
  const ongoing = result.events.filter(event => event.ongoing)

  const eventRow = event => (
    <li key={event.id} className="event-row">
      <div className="event-when">{dateRange(event)}</div>
      <div className="event-what">
        <strong>
          {event.title}
          {event.category && (
            <em className="event-tag" style={{ background: CATEGORY_COLORS[event.category] }}>
              {event.category}
            </em>
          )}
        </strong>
        <span>
          {event.destination.name} · ~{Math.round(event.destination.driveMinutes)} min drive
        </span>
        {event.description && <p>{event.description}</p>}
      </div>
      {webURL(event.url || event.destination.url) && (
        <a href={webURL(event.url || event.destination.url)}
           target="_blank" rel="noreferrer">
          Details
        </a>
      )}
    </li>
  )

  return (
    <div className="events-view">
      <h2>
        Next {result.days} days within {result.minutes} minutes of {settings.postcode},
        nearest first
      </h2>
      {special.length === 0 && (
        <p className="notice">
          {ongoing.length > 0
            ? 'No one-off events this week — just the ongoing programmes below.'
            : 'No events found — either a quiet week, or the scraper hasn’t run yet.'}
        </p>
      )}
      <ul className="event-list">{special.map(eventRow)}</ul>

      {ongoing.length > 0 && (
        <>
          <h3 className="events-subhead">Ongoing — running for weeks or months</h3>
          <ul className="event-list">{ongoing.map(eventRow)}</ul>
        </>
      )}

      <Excluded excluded={result.excluded} minutes={result.minutes}
                days={result.days} />
    </div>
  )
}

// Events that exist but did not qualify, and why.
//
// Without this a source reports five events on the Sources page and shows
// none here, with nothing to explain the difference. The settings are
// usually right and the answer is usually "further than an hour away" —
// but that has to be said, not left to be guessed at.
function Excluded({ excluded, minutes, days }) {
  if (!excluded) return null
  const { tooFar = 0, later = 0, wrongCategory = 0 } = excluded
  if (!tooFar && !later && !wrongCategory) return null

  const plural = n => (n === 1 ? 'event is' : 'events are')
  const parts = []
  if (tooFar) {
    parts.push(
      `${tooFar} ${plural(tooFar)} further than ${minutes} minutes away` +
      (excluded.nearestName
        ? ` (nearest: ${excluded.nearestName}, about ${
            Math.round(excluded.nearestMinutes)} min)`
        : ''))
  }
  if (later) parts.push(`${later} ${plural(later)} beyond the next ${days} days`)
  if (wrongCategory) {
    parts.push(`${wrongCategory} ${plural(wrongCategory)} in categories you have turned off`)
  }

  return (
    <p className="notice excluded">
      Not shown: {parts.join('; ')}. Change the limits in{' '}
      <Link to="/settings">Settings</Link>.
    </p>
  )
}
