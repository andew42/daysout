import { useEffect, useState } from 'react'
import { addSource, deleteSource, fetchSources, setSourceEnabled } from './api.jsx'
import { ALL_CATEGORIES } from './settings.jsx'

// What each extractor does, in the terms someone adding a site can judge.
// 'auto' probes the URL and picks one of the others, which is the right
// answer for a site nobody has looked at yet.
const KIND_LABELS = {
  auto: 'Work it out automatically',
  browser: 'Render the page in a browser first',
  ical: 'Calendar feed (.ics)',
  jsonld: 'Event data on the page itself',
  sitemap: 'Crawl the site’s event pages',
}

// The scraper records what it found when it last probed a source. Say what
// that means rather than showing the raw field: "sitemap" on its own tells
// you nothing about whether the site is contributing events.
function verdict(source) {
  if (!source.lastStatus) return 'not visited yet'
  if (source.lastStatus === 'nothing usable') return 'nothing machine-readable found'
  return `publishes: ${source.lastStatus}`
}

export default function SourcesView() {
  const [sources, setSources] = useState(null)
  const [kinds, setKinds] = useState(['auto'])
  const [form, setForm] = useState({ url: '', category: 'venue', kind: 'auto' })
  const [error, setError] = useState('')
  const [added, setAdded] = useState('')
  const [busy, setBusy] = useState(false)

  const reload = () =>
    fetchSources()
      .then(result => {
        setSources(result.sources)
        setKinds(result.kinds)
      })
      .catch(e => setError(e.message))

  useEffect(() => {
    reload()
  }, [])

  const update = patch => setForm(f => ({ ...f, ...patch }))

  const submit = async event => {
    event.preventDefault()
    setError('')
    setAdded('')
    setBusy(true)
    try {
      const source = await addSource(form)
      setAdded(source.name)
      setForm({ ...form, url: '' })
      await reload()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const toggle = async source => {
    setError('')
    try {
      await setSourceEnabled(source.name, !source.enabled)
      await reload()
    } catch (e) {
      setError(e.message)
    }
  }

  const remove = async source => {
    setError('')
    try {
      await deleteSource(source.name)
      await reload()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="sources-view">
      <h2>Sources</h2>
      <p className="sources-intro">
        Sites the scraper visits looking for events. Adding one here only
        writes it down — this server never fetches anything itself. The
        scraper visits it on its next run (daily, 05:30) and reports back
        what it found.
      </p>

      <form className="settings-view" onSubmit={submit}>
        <label>
          Website address
          <input
            type="text"
            value={form.url}
            onChange={e => update({ url: e.target.value })}
            placeholder="e.g. ngs.org.uk/find-a-garden"
            autoFocus
          />
        </label>

        <label>
          Category for its events
          <select value={form.category} onChange={e => update({ category: e.target.value })}>
            {ALL_CATEGORIES.map(category => (
              <option key={category.id} value={category.id}>{category.label}</option>
            ))}
          </select>
        </label>

        <label>
          How to read it
          <select value={form.kind} onChange={e => update({ kind: e.target.value })}>
            {kinds.map(kind => (
              <option key={kind} value={kind}>{KIND_LABELS[kind] || kind}</option>
            ))}
          </select>
        </label>

        <button type="submit" disabled={busy || !form.url.trim()}>
          {busy ? 'Adding…' : 'Add site'}
        </button>
      </form>

      {error && <p className="notice error">{error}</p>}
      {added && (
        <p className="notice">
          Added as <strong>{added}</strong>. It will be visited on the next
          scrape; its verdict appears in the list below afterwards.
        </p>
      )}

      {!sources ? (
        <p className="notice">Loading…</p>
      ) : (
        <ul className="source-list">
          {sources.map(source => (
            <li key={source.name} className={source.enabled ? 'source' : 'source disabled'}>
              <div className="source-main">
                <strong>{source.name}</strong>
                <a href={source.url} target="_blank" rel="noreferrer">{source.url}</a>
                <span className="source-meta">
                  {source.category || 'uncategorised'} · {KIND_LABELS[source.kind] || source.kind}
                  {' · '}{verdict(source)}
                </span>
                {source.notes && <span className="source-notes">{source.notes}</span>}
              </div>
              <div className="source-actions">
                <button type="button" onClick={() => toggle(source)}>
                  {source.enabled ? 'Disable' : 'Enable'}
                </button>
                {/* Built-in candidates are re-added by the scraper if
                    deleted, so only sites added here offer Remove. */}
                {source.userAdded && (
                  <button type="button" className="danger" onClick={() => remove(source)}>
                    Remove
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
