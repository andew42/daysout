import { useEffect, useState } from 'react'
import { fetchEvents } from './api.jsx'
import { CATEGORY_COLORS, loadSettings } from './settings.jsx'

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
      {(event.url || event.destination.url) && (
        <a href={event.url || event.destination.url} target="_blank" rel="noreferrer">
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
    </div>
  )
}
