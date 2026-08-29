import { useEffect, useState } from 'react'
import { fetchEvents } from './api.jsx'
import { loadSettings } from './settings.jsx'

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

  return (
    <div className="events-view">
      <h2>
        Next {result.days} days within {result.minutes} minutes of {settings.postcode},
        nearest first
      </h2>
      {result.events.length === 0 && (
        <p className="notice">
          No events found — either a quiet week, or the scraper hasn’t populated
          the events table yet.
        </p>
      )}
      <ul className="event-list">
        {result.events.map(event => (
          <li key={event.id} className="event-row">
            <div className="event-when">{dateRange(event)}</div>
            <div className="event-what">
              <strong>{event.title}</strong>
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
        ))}
      </ul>
    </div>
  )
}
