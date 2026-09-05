package store

import (
	"database/sql"
	"sort"
)

// Source is one of the scraper's sources, with what it is contributing.
//
// There is no sources table any more. Sources lived in the database for a
// while, so that trying a new listing site was a row rather than a
// release and the web UI could add one. That did not survive contact with
// the sites: they differ so much that reading one takes a parser written
// against it, and a row added without that investigation reported an empty
// site for ever. Every source is written in code now, this page lists
// them, and the only thing it can do to one is ask for it to be updated.
type Source struct {
	Name string `json:"name"`

	// What this source is actually contributing — the question the page
	// exists to answer. A verdict about what a site publishes says
	// nothing about whether any of it reached the map.
	Events       int `json:"events"`
	Destinations int `json:"destinations"`

	// The scraper's own account of the last time it ran this source.
	LastRun     string `json:"lastRun"`
	LastRunOK   bool   `json:"lastRunOK"`
	LastMessage string `json:"lastMessage"`
}

// CodeSources are every source the scraper has, named here because the
// database no longer holds a list of them.
//
// Kept in step with scraper/daysout_scraper/sources/__init__.py by a test:
// a name missing from here is a source that has quietly stopped being
// listed, and nobody would notice until they wondered where its events
// were coming from.
var CodeSources = []string{
	"wikidata", "english_heritage", "historic-houses", "shuttleworth-events",
	"uk-craft-fairs", "lamport-hall", "waddesdon", "food-festivals-uk",
	"ngs-open-gardens", "iacf", "rhs-events", "stonor-whats-on",
}

// Sources returns every source with what it is contributing, for the UI.
//
// Ordered by what each has produced, so what is working is at the top and
// a source reporting nothing sits at the bottom of a short list where it
// is easy to spot.
func (s *Store) Sources() ([]Source, error) {

	sources := make([]Source, 0, len(CodeSources))
	for _, name := range CodeSources {
		source := Source{Name: name}

		if err := s.DB.QueryRow(
			`SELECT (SELECT COUNT(*) FROM events WHERE source = ?),
			        (SELECT COUNT(*) FROM destinations WHERE source = ?)`,
			name, name).Scan(&source.Events, &source.Destinations); err != nil {
			return nil, err
		}

		var ok sql.NullBool
		var started, message sql.NullString
		// A source that has never run is not an error: it is a source
		// added since the last scrape, and the page should say so rather
		// than fail.
		err := s.DB.QueryRow(
			`SELECT started_at, ok, message FROM scrape_runs
			 WHERE source = ? ORDER BY id DESC LIMIT 1`,
			name).Scan(&started, &ok, &message)
		if err != nil && err != sql.ErrNoRows {
			return nil, err
		}
		source.LastRun = started.String
		source.LastRunOK = ok.Valid && ok.Bool
		source.LastMessage = message.String

		sources = append(sources, source)
	}

	sort.SliceStable(sources, func(i, j int) bool {
		if sources[i].Events != sources[j].Events {
			return sources[i].Events > sources[j].Events
		}
		if sources[i].Destinations != sources[j].Destinations {
			return sources[i].Destinations > sources[j].Destinations
		}
		return sources[i].Name < sources[j].Name
	})
	return sources, nil
}

// LatestRun returns the scraper's verdict from the most recent run of a
// source: whether it succeeded and the message it recorded.
func (s *Store) LatestRun(name string) (bool, string) {

	var ok sql.NullBool
	var message string
	err := s.DB.QueryRow(
		`SELECT ok, message FROM scrape_runs WHERE source = ?
		 ORDER BY id DESC LIMIT 1`, name).Scan(&ok, &message)
	if err != nil {
		return false, ""
	}
	return ok.Valid && ok.Bool, message
}

// SourceRow is one event or place a source has contributed, for the list
// behind the contribution pill.
//
// Deliberately not the Destination and Event types the map and events views
// use: those carry drive times from a postcode, which is a question about
// where you live and has nothing to do with what a source produced.
type SourceRow struct {
	Title    string `json:"title"`
	When     string `json:"when"`
	Where    string `json:"where"`
	Postcode string `json:"postcode"`
	Category string `json:"category"`
	URL      string `json:"url"`
}

// SourceContribution is everything a source has put in the database.
type SourceContribution struct {
	Name              string      `json:"name"`
	Events            []SourceRow `json:"events"`
	Destinations      []SourceRow `json:"destinations"`
	EventsTotal       int         `json:"eventsTotal"`
	DestinationsTotal int         `json:"destinationsTotal"`
}

// sourceRowLimit keeps one badly-behaved source from sending thousands of
// rows to a browser; the totals still report the true size.
const sourceRowLimit = 200

// Contribution lists what one source has actually contributed.
//
// Events first and soonest first: the question behind the pill is "what
// did this give me?", and a list starting with things long past answers a
// different one.
func (s *Store) Contribution(name string) (SourceContribution, error) {

	result := SourceContribution{
		Name: name, Events: []SourceRow{}, Destinations: []SourceRow{},
	}

	events, err := s.DB.Query(
		`SELECT e.title, e.start_date, e.end_date, e.category, e.url,
		        d.name, d.postcode
		 FROM events e JOIN destinations d ON d.id = e.destination_id
		 WHERE e.source = ?
		 ORDER BY e.start_date DESC LIMIT ?`, name, sourceRowLimit)
	if err != nil {
		return result, err
	}
	defer events.Close()
	for events.Next() {
		var row SourceRow
		var start, end string
		if err := events.Scan(&row.Title, &start, &end, &row.Category,
			&row.URL, &row.Where, &row.Postcode); err != nil {
			return result, err
		}
		row.When = start
		if end != start {
			row.When = start + " – " + end
		}
		result.Events = append(result.Events, row)
	}
	if err := events.Err(); err != nil {
		return result, err
	}

	places, err := s.DB.Query(
		`SELECT name, category, postcode, url FROM destinations
		 WHERE source = ? ORDER BY name LIMIT ?`, name, sourceRowLimit)
	if err != nil {
		return result, err
	}
	defer places.Close()
	for places.Next() {
		var row SourceRow
		if err := places.Scan(&row.Title, &row.Category, &row.Postcode,
			&row.URL); err != nil {
			return result, err
		}
		result.Destinations = append(result.Destinations, row)
	}
	if err := places.Err(); err != nil {
		return result, err
	}

	if err := s.DB.QueryRow(`SELECT COUNT(*) FROM events WHERE source = ?`,
		name).Scan(&result.EventsTotal); err != nil {
		return result, err
	}
	err = s.DB.QueryRow(`SELECT COUNT(*) FROM destinations WHERE source = ?`,
		name).Scan(&result.DestinationsTotal)
	return result, err
}
