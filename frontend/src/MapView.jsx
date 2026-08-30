import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchDestinations, fetchStatus } from './api.jsx'
import { CATEGORY_COLORS, loadSettings } from './settings.jsx'
import { webURL } from './links.jsx'

// Register the pmtiles:// protocol once for the whole app. Pass the handler
// by reference: MapLibre calls it with (requestParameters, abortController)
// and pmtiles needs both, so wrapping it in a one-argument arrow function
// makes every tile request throw and leaves the map silently blank.
const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

// The sprite lives at a versioned path in the basemap assets, and which
// version is current changes with the asset bundle. Probe rather than
// hardcode: a wrong sprite path is an easy way to lose all the map's icons.
const SPRITE_PATHS = ['/basemap/sprites/v4/light', '/basemap/sprites/light']

async function resolveSprite() {
  for (const path of SPRITE_PATHS) {
    try {
      const response = await fetch(path + '.json', { method: 'HEAD' })
      if (response.ok) return location.origin + path
    } catch {
      // Try the next candidate.
    }
  }
  return null
}

// Basemap style using the offline tile archive and locally served fonts and
// sprites (populated by setup/get-tiles.sh). When tiles are missing we fall
// back to a plain background so markers still show.
function buildStyle(tilesAvailable, spriteUrl) {
  const style = {
    version: 8,
    glyphs: '/basemap/fonts/{fontstack}/{range}.pbf',
    sources: {},
    layers: [{
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#e8ece4' },
    }],
  }
  if (spriteUrl) style.sprite = spriteUrl
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

export function popupHTML(destination) {
  // Venues created from an event have no description, and printed a blank
  // line where one would go.
  const lines = [`<strong>${escapeHTML(destination.name)}</strong>`]
  if (destination.description) lines.push(escapeHTML(destination.description))
  const events = destination.upcomingEvents > 0
    ? `, ${destination.upcomingEvents} upcoming event${destination.upcomingEvents > 1 ? 's' : ''}`
    : ''
  lines.push(`~${Math.round(destination.driveMinutes)} min drive${events}`)
  if (destination.postcode) lines.push(escapeHTML(destination.postcode))
  const link = webURL(destination.url)
  if (link) {
    lines.push(`<a href="${escapeHTML(link)}" target="_blank" ` +
               `rel="noreferrer">Website</a>`)
  }
  return lines.join('<br>')
}

// Names and descriptions come from scraped pages, so they reach this
// as untrusted text and must not be pasted into HTML as they stand.
function escapeHTML(text) {
  return String(text).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]))
}

// Layers the basemap style draws from; if the archive has none of these the
// map renders blank with no error, so check rather than leave the user
// staring at an empty screen.
const EXPECTED_SOURCE_LAYERS = ['earth', 'water', 'roads', 'places']

export default function MapView() {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const markersRef = useRef([])
  const [error, setError] = useState('')
  const [mapWarning, setMapWarning] = useState('')
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
      const spriteUrl = tilesAvailable ? await resolveSprite() : null
      if (cancelled) return

      const map = new maplibregl.Map({
        container: containerRef.current,
        style: buildStyle(tilesAvailable, spriteUrl),
        center: [home.lon, home.lat],
        zoom: 9,
        attributionControl: tilesAvailable ? {} : false,
      })
      mapRef.current = map
      map.addControl(new maplibregl.NavigationControl(), 'top-right')

      // A basemap that fails to load is otherwise silent — the canvas just
      // stays empty — so say what went wrong.
      map.on('error', event => {
        const message = event?.error?.message || String(event?.error || 'unknown error')
        setMapWarning(`Basemap problem: ${message}`)
      })

      // Tiles can load fine and still draw nothing if the archive's layers
      // aren't the ones this style expects. Check once, after the first
      // render settles.
      if (tilesAvailable) {
        map.once('idle', () => {
          const present = EXPECTED_SOURCE_LAYERS.filter(sourceLayer =>
            map.querySourceFeatures('protomaps', { sourceLayer }).length > 0)
          if (present.length === 0) {
            setMapWarning(
              'The tile archive served none of the layers this style draws ' +
              '(earth, water, roads, places): it may be incomplete, or built to a ' +
              'different basemap version. Re-run setup/get-tiles.sh to rebuild it.')
          }
        })
      }

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
          color: CATEGORY_COLORS[destination.category] || '#666666',
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
      {mapWarning && <p className="notice error">{mapWarning}</p>}
      <div ref={containerRef} className="map-container" />
    </div>
  )
}
