import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import MapView from './MapView.jsx'
import EventsView from './EventsView.jsx'
import SettingsView from './SettingsView.jsx'
import SourcesView from './SourcesView.jsx'
import { fetchStatus } from './api.jsx'
import { loadSettings } from './settings.jsx'

function StatusFooter() {
  const [status, setStatus] = useState(null)

  useEffect(() => {
    fetchStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  if (!status) return null
  const lastScrape = status.scrapes.length
    ? `last scrape ${status.scrapes[status.scrapes.length - 1].startedAt.slice(0, 10)}`
    : 'scraper has not run yet'
  return (
    <footer className="status-footer">
      {status.destinations} destinations · {status.events} events ·{' '}
      {status.postcodes.toLocaleString()} postcodes ·{' '}
      {status.tilesAvailable ? 'offline map ready' : 'map tiles not installed'} · {lastScrape}
    </footer>
  )
}

// Until a home postcode is configured every view redirects to settings.
// Checked at render time (not in App's body) so it re-evaluates on navigation.
function RequireConfigured({ children }) {
  return loadSettings().postcode !== '' ? children : <Navigate to="/settings" replace />
}

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Days Out</h1>
        <nav>
          <NavLink to="/" end>Map</NavLink>
          <NavLink to="/events">Events</NavLink>
          <NavLink to="/sources">Sources</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<RequireConfigured><MapView /></RequireConfigured>} />
          <Route path="/events" element={<RequireConfigured><EventsView /></RequireConfigured>} />
          <Route path="/sources" element={<SourcesView />} />
          <Route path="/settings" element={<SettingsView />} />
        </Routes>
      </main>
      <StatusFooter />
    </div>
  )
}
