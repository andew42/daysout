import { useEffect, useState } from 'react'
import { addSource, deleteSource, fetchSources, updateSource } from './api.jsx'
import { ALL_CATEGORIES } from './settings.jsx'

// What each extractor does, in the terms someone adding a site can judge.
// 'auto' probes the URL and picks one of the others, which is the right
// answer for a site nobody has looked at yet.
const KIND_LABELS = {
  auto: 'Work it out automatically',
  wpevents: 'WordPress events API (best, if the site has one)',
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

// What a source is actually contributing — the only number that answers
// "is this site worth keeping?". A verdict of "sitemap" and a count of
// zero mean the same thing in the end, and only one of them says so.
function Contribution({ source }) {
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
  if (!source.events && !source.destinations) {
    return (
      <span className="contribution none">
        {source.lastRun ? 'no events' : 'not run yet'}
      </span>
    )
  }
  return (
    <span className="contribution">
      <strong>{plural(source.events, 'event')}</strong>
      {source.destinations > 0 && ` · ${plural(source.destinations, 'place')}`}
    </span>
  )
}

// Removing a source is not undoable and takes its events off the map, so
// say which one and what goes with it before doing it.
function ConfirmRemove({ source, onCancel, onConfirm, busy }) {
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  const contributed = source.events > 0 || source.destinations > 0

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-remove-title"
        onClick={e => e.stopPropagation()}
      >
        <h3 id="confirm-remove-title">Remove {source.name}?</h3>
        <p>
          {contributed
            ? `Its ${source.events} event${source.events === 1 ? '' : 's'} \
will be taken off the map. Nothing refreshes them once the source is gone, \
so they cannot be left behind.`
            : 'It has contributed no events, so nothing comes off the map.'}
        </p>
        <p className="modal-note">
          The scraper will not add it back. You can add the site again later.
        </p>
        <div className="modal-actions">
          <button type="button" onClick={onCancel} autoFocus>Cancel</button>
          <button type="button" className="danger" disabled={busy}
                  onClick={onConfirm}>
            {busy ? 'Removing…' : 'Remove'}
          </button>
        </div>
      </div>
    </div>
  )
}

// What the scraper did, in its own words. The log matters more than the
// verdict: it names the pages it looked at, how many events it read, and
// the venue of any event it could not place.
function TestResult({ result }) {
  return (
    <div className={result.ok ? 'test-result ok' : 'test-result bad'}>
      <strong>
        {result.ok ? 'Found something' : 'Nothing usable'}
        {result.seconds ? ` · ${result.seconds}s` : ''}
      </strong>
      {result.message && <div className="test-message">{result.message}</div>}
      {result.output && <pre>{result.output}</pre>}
    </div>
  )
}

export default function SourcesView() {
  const [sources, setSources] = useState(null)
  const [kinds, setKinds] = useState(['auto'])
  const [form, setForm] = useState({
    url: '', category: 'venue', kind: 'auto', venueName: '', venuePostcode: '',
  })
  const [error, setError] = useState('')
  const [added, setAdded] = useState('')
  const [busy, setBusy] = useState(false)
  // Which source is being updated, and the last result for each.
  const [updating, setUpdating] = useState('')
  // The source awaiting confirmation before removal, if any.
  const [confirming, setConfirming] = useState(null)
  const [removing, setRemoving] = useState(false)
  const [results, setResults] = useState({})

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

  const setField = patch => setForm(f => ({ ...f, ...patch }))

  const submit = async event => {
    event.preventDefault()
    setError('')
    setAdded('')
    setBusy(true)
    try {
      const source = await addSource(form)
      setAdded(source.name)
      setForm({ ...form, url: '', venueName: '', venuePostcode: '' })
      await reload()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const update = async source => {
    setError('')
    setUpdating(source.name)
    try {
      const result = await updateSource(source.name)
      setResults(r => ({ ...r, [source.name]: result }))
      await reload()
    } catch (e) {
      setResults(r => ({ ...r, [source.name]: { ok: false, message: e.message } }))
    } finally {
      setUpdating('')
    }
  }

  const remove = async source => {
    setError('')
    setRemoving(true)
    try {
      await deleteSource(source.name)
      setConfirming(null)
      await reload()
    } catch (e) {
      setError(e.message)
      setConfirming(null)
    } finally {
      setRemoving(false)
    }
  }

  return (
    <div className="sources-view">
      {confirming && (
        <ConfirmRemove
          source={confirming}
          busy={removing}
          onCancel={() => setConfirming(null)}
          onConfirm={() => remove(confirming)}
        />
      )}
      <h2>Sources</h2>
      <p className="sources-intro">
        Sites the scraper visits looking for events. Adding one here only
        writes it down — this server never fetches anything itself. The
        scraper visits it on its next run (daily, 05:30) — or press
        <strong> Update</strong> to crawl that one site now and see what came
        back. An update is a full crawl, so it can take a few minutes on a
        large site: the scraper stays at one polite request per second.
      </p>

      <form className="settings-view" onSubmit={submit}>
        <label>
          Website address
          <input
            type="text"
            value={form.url}
            onChange={e => setField({ url: e.target.value })}
            placeholder="e.g. ngs.org.uk/find-a-garden"
            autoFocus
          />
        </label>

        <label>
          Category for its events
          <select value={form.category} onChange={e => setField({ category: e.target.value })}>
            {ALL_CATEGORIES.map(category => (
              <option key={category.id} value={category.id}>{category.label}</option>
            ))}
          </select>
        </label>

        <label>
          How to read it
          <select value={form.kind} onChange={e => setField({ kind: e.target.value })}>
            {kinds.map(kind => (
              <option key={kind} value={kind}>{KIND_LABELS[kind] || kind}</option>
            ))}
          </select>
        </label>

        <label>
          Venue postcode <span className="hint">optional — for a site that
          is one place, whose event pages never repeat the address</span>
          <input
            type="text"
            value={form.venuePostcode}
            onChange={e => setField({ venuePostcode: e.target.value })}
            placeholder="e.g. SG18 9EP"
          />
        </label>

        <label>
          Venue name <span className="hint">optional</span>
          <input
            type="text"
            value={form.venueName}
            onChange={e => setField({ venueName: e.target.value })}
            placeholder="e.g. Shuttleworth"
          />
        </label>

        <button type="submit" disabled={busy || !form.url.trim()}>
          {busy ? 'Adding…' : 'Add site'}
        </button>
      </form>

      {error && <p className="notice error">{error}</p>}
      {added && (
        <p className="notice">
          Added as <strong>{added}</strong>. Press <strong>Update</strong>
          on it below to see straight away whether it publishes anything
          usable; otherwise the next scrape will pick it up.
        </p>
      )}

      {!sources ? (
        <p className="notice">Loading…</p>
      ) : (
        <ul className="source-list">
          {sources.map(source => (
            <li key={source.name} className={source.enabled ? 'source' : 'source disabled'}>
              <div className="source-main">
                <strong>
                  {source.name}
                  <Contribution source={source} />
                </strong>
                {source.url
                  ? <a href={source.url} target="_blank" rel="noreferrer">{source.url}</a>
                  : <span className="source-meta">built into the scraper</span>}
                {!source.builtIn && (
                  <span className="source-meta">
                    {source.category || 'uncategorised'} ·{' '}
                    {KIND_LABELS[source.kind] || source.kind} · {verdict(source)}
                  </span>
                )}
                {/* The scraper's own words about its last run say more than
                    any count: how many events it read, and how many of those
                    it could place. */}
                {source.lastMessage && (
                  <span className={source.lastRunOK ? 'source-run' : 'source-run bad'}>
                    last run: {source.lastMessage}
                  </span>
                )}
                {source.notes && !source.builtIn && (
                  <span className="source-notes">{source.notes}</span>
                )}
              </div>
              <div className="source-actions">
                <button
                  type="button"
                  onClick={() => update(source)}
                  disabled={updating !== ''}
                >
                  {updating === source.name ? 'Updating…' : 'Update'}
                </button>
                {/* Sources written into the scraper have no row to remove. */}
                {!source.builtIn && (
                  <button type="button" className="danger"
                          onClick={() => setConfirming(source)}>
                    Remove
                  </button>
                )}
              </div>
              {results[source.name] && <TestResult result={results[source.name]} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
