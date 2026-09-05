import { useState, useEffect } from 'react'
import { fetchContribution, fetchSources, updateSource } from './api.jsx'
import { webURL } from './links.jsx'

// This page could once add and remove sources. Sources were rows in a
// table then, read by a generic engine that picked an extractor by kind,
// so trying a new listing site was an INSERT rather than a release.
//
// It did not work out. The sites differ too much: reading one takes a
// parser written against it, after somebody has looked at what it actually
// publishes, and rows added without that reported an empty site for ever.
// Every source is written in code now, so the list is fixed and the page
// is a report on it. Update is the one thing it can still ask for.

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

// What a source is actually contributing — the only number that answers
// "is this working?".
//
// Clickable when there is something to show: the count says a source is
// working, and the rows say whether what it produced is any good, which is
// the next thing you want to know every time.
function Contribution({ source, expanded, onToggle }) {
  if (!source.events && !source.destinations) {
    return (
      <span className="contribution none">
        {source.lastRun ? 'no events' : 'not run yet'}
      </span>
    )
  }
  return (
    <button
      type="button"
      className="contribution"
      aria-expanded={expanded}
      onClick={onToggle}
      title="Show what this source produced"
    >
      <strong>{plural(source.events, 'event')}</strong>
      {source.destinations > 0 && ` · ${plural(source.destinations, 'place')}`}
      <span className="contribution-caret">{expanded ? '▾' : '▸'}</span>
    </button>
  )
}

// The rows themselves. Events soonest-last so the newest are at the top,
// which is where a source's current output is.
function ContributionList({ contribution }) {
  if (!contribution) return <p className="notice">Loading…</p>
  if (contribution.error) return <p className="notice error">{contribution.error}</p>

  const { events, destinations, eventsTotal, destinationsTotal } = contribution
  const more = (shown, total) =>
    total > shown ? ` (showing ${shown} of ${total})` : ''

  return (
    <div className="contribution-list">
      {events.length > 0 && (
        <>
          <h4>
            {plural(eventsTotal, 'event')}
            {more(events.length, eventsTotal)}
          </h4>
          <ul>
            {events.map((event, i) => (
              <li key={`e${i}`}>
                <span className="when">{event.when}</span>
                {event.url
                  ? <a href={webURL(event.url)} target="_blank" rel="noreferrer">{event.title}</a>
                  : <span>{event.title}</span>}
                <span className="where">
                  {event.where}{event.postcode && ` · ${event.postcode}`}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {destinations.length > 0 && (
        <>
          <h4>
            {plural(destinationsTotal, 'place')}
            {more(destinations.length, destinationsTotal)}
          </h4>
          <ul>
            {destinations.map((place, i) => (
              <li key={`d${i}`}>
                <span>{place.title}</span>
                <span className="where">
                  {place.category}{place.postcode && ` · ${place.postcode}`}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

// What the scraper did, in its own words. The log matters more than any
// count: it names the pages it looked at, how many events it read, and the
// venue of any event it could not place.
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
  const [error, setError] = useState('')
  // Which source is being updated, and the last result for each.
  const [updating, setUpdating] = useState('')
  const [results, setResults] = useState({})
  // Which source's rows are open, and what we have loaded for each.
  const [openSource, setOpenSource] = useState('')
  const [contributions, setContributions] = useState({})

  const reload = () =>
    fetchSources()
      .then(result => setSources(result.sources))
      .catch(e => setError(e.message))

  useEffect(() => {
    reload()
  }, [])

  const toggleRows = async source => {
    if (openSource === source.name) {
      setOpenSource('')
      return
    }
    setOpenSource(source.name)
    // Always refetch: an Update may have changed what this source holds.
    setContributions(c => ({ ...c, [source.name]: null }))
    try {
      const rows = await fetchContribution(source.name)
      setContributions(c => ({ ...c, [source.name]: rows }))
    } catch (e) {
      setContributions(c => ({ ...c, [source.name]: { error: e.message } }))
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

  return (
    <div className="sources-view">
      <h2>Sources</h2>
      <p className="sources-intro">
        Where the events come from. Each of these has a parser written for
        it, because these sites publish in too many different shapes to be
        read by one. The scraper visits them daily at 05:30 — or press
        <strong> Update</strong> to crawl one now and see what came back. An
        update is a full crawl, so it can take a few minutes on a large
        site: the scraper stays at one polite request per second.
      </p>

      {error && <p className="notice error">{error}</p>}

      {!sources ? (
        <p className="notice">Loading…</p>
      ) : (
        <ul className="source-list">
          {sources.map(source => (
            <li key={source.name} className="source">
              <div className="source-main">
                <strong>
                  {source.name}
                  <Contribution
                    source={source}
                    expanded={openSource === source.name}
                    onToggle={() => toggleRows(source)}
                  />
                </strong>
                {/* The scraper's own words about its last run say more than
                    any count: how many events it read, and how many of
                    those it could place. */}
                {source.lastMessage && (
                  <span className={source.lastRunOK ? 'source-run' : 'source-run bad'}>
                    last run: {source.lastMessage}
                  </span>
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
              </div>
              {openSource === source.name && (
                <ContributionList contribution={contributions[source.name]} />
              )}
              {results[source.name] && <TestResult result={results[source.name]} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
