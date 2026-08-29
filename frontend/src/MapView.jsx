import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchDestinations, fetchStatus } from './api.jsx'
import { loadSettings } from './settings.jsx'

// Register the pmtiles:// protocol once for the whole app.
const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', tile => protocol.tile(tile))

const categoryColors = {
  'historic-house': '#8c4a2f',
  garden: '#2f6b4e',
  airfield: '#3a5da8',
}

// Basemap style using the offline tile archive and locally served fonts and
// sprites (populated by setup/get-tiles.sh). When tiles are missing we fall
// back to a plain background so markers still show.
function buildStyle(tilesAvailable) {
  const style = {
    version: 8,
    glyphs: '/basemap/fonts/{fontstack}/{range}.pbf',
    sprite: location.origin + '/basemap/sprites/v4/light',
    sources: {},
    layers: [{
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#e8ece4' },
    }],
  }
  if (tilesAvailable) {
    style.sources.protomaps = {
      type: 'vector',
      url: 'pmtiles://' + location.origin + '/tiles/uk.pmtiles',
      attribution: '© OpenStreetMap contributors',
    }
    style.layers = layers('protomaps', namedFlavor('light'), { lang: 'en' })
  }
  return style
}

// Approximate drive-time limit as a circle: invert the drive-time formula to
// get the crow-flies radius, then build a geojson polygon around home.
function radiusCircle(home, minutes) {
  const radiusKm = (minutes / 60) * 60 / 1.3
  const coordinates = []
  for (let i = 0; i <= 72; i++) {
    const angle = (i / 72) * 2 * Math.PI
    const dLat = (radiusKm / 111.32) * Math.cos(angle)
    const dLon = (radiusKm / (111.32 * Math.cos(home.lat * Math.PI / 180))) * Math.sin(angle)
    coordinates.push([home.lon + dLon, home.lat + dLat])
  }
  return {
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [coordinates] },
  }
}

function popupHTML(destination) {
  const link = destination.url
    ? `<a href="${destination.url}" target="_blank" rel="noreferrer">Website</a>`
    : ''
  const events = destination.upcomingEvents > 0
    ? `<br>${destination.upcomingEvents} upcoming event${destination.upcomingEvents > 1 ? 's' : ''}`
    : ''
  return `<strong>${destination.name}</strong><br>
    ${destination.description}<br>
    ~${Math.round(destination.driveMinutes)} min drive${events}<br>${link}`
}

export default function MapView() {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const markersRef = useRef([])
  const [error, setError] = useState('')
  const [summary, setSummary] = useState('Loading…')

  useEffect(() => {
    const settings = loadSettings()
    let cancelled = false

    async function load() {
      let tilesAvailable = false
      try {
        tilesAvailable = (await fetchStatus()).tilesAvailable
      } catch {
        // Status is best-effort; fall back to the plain background.
      }

      let result
      try {
        result = await fetchDestinations(settings)
      } catch (e) {
        if (!cancelled) setError(e.message)
        return
      }
      if (cancelled) return

      const home = result.home
      const map = new maplibregl.Map({
        container: containerRef.current,
        style: buildStyle(tilesAvailable),
        center: [home.lon, home.lat],
        zoom: 9,
        attributionControl: tilesAvailable ? {} : false,
      })
      mapRef.current = map
      map.addControl(new maplibregl.NavigationControl(), 'top-right')

      map.on('load', () => {
        map.addSource('drive-limit', { type: 'geojson', data: radiusCircle(home, result.minutes) })
        map.addLayer({
          id: 'drive-limit-line',
          type: 'line',
          source: 'drive-limit',
          paint: { 'line-color': '#2f6b4e', 'line-width': 1.5, 'line-dasharray': [3, 3] },
        })
      })

      const homeMarker = new maplibregl.Marker({ color: '#222222' })
        .setLngLat([home.lon, home.lat])
        .setPopup(new maplibregl.Popup().setText(`Home: ${settings.postcode}`))
        .addTo(map)
      markersRef.current.push(homeMarker)

      for (const destination of result.destinations) {
        const marker = new maplibregl.Marker({
          color: categoryColors[destination.category] || '#666666',
        })
          .setLngLat([destination.lon, destination.lat])
          .setPopup(new maplibregl.Popup({ maxWidth: '280px' }).setHTML(popupHTML(destination)))
          .addTo(map)
        markersRef.current.push(marker)
      }

      setSummary(
        `${result.destinations.length} destinations within ${result.minutes} minutes` +
        (tilesAvailable ? '' : ' — map tiles not installed, run setup/get-tiles.sh'),
      )
    }

    load()
    return () => {
      cancelled = true
      markersRef.current.forEach(marker => marker.remove())
      markersRef.current = []
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [])

  return (
    <div className="map-view">
      {error ? <p className="notice error">{error}</p> : <p className="map-summary">{summary}</p>}
      <div ref={containerRef} className="map-container" />
    </div>
  )
}
