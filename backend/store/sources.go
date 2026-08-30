package store

import (
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"time"
)

// Source is a row of the sources table: a site the scraper visits looking
// for events. Sources live in the database rather than in code so that
// trying a new listing site is a row, not a release — which is what lets
// the UI add one.
type Source struct {
	Name     string `json:"name"`
	URL      string `json:"url"`
	Kind     string `json:"kind"`
	Category string `json:"category"`
	Enabled  bool   `json:"enabled"`
	Notes    string `json:"notes"`
	Added    string `json:"added"`
	// A site that is one venue: used only when an event brings no venue
	// of its own, which is the usual case on an attraction's own website.
	VenueName     string `json:"venueName"`
	VenuePostcode string `json:"venuePostcode"`
	LastStatus    string `json:"lastStatus"`
	// UserAdded rows may be deleted; seeded ones may only be disabled,
	// because the scraper re-inserts any candidate missing from the table.
	UserAdded bool `json:"userAdded"`

	// What this source is actually contributing. A verdict like "sitemap"
	// says what a site publishes; these say whether any of it reached the
	// map, which is the only question that matters.
	Events       int `json:"events"`
	Destinations int `json:"destinations"`

	// The scraper's own account of the last time it ran this source.
	LastRun     string `json:"lastRun"`
	LastRunOK   bool   `json:"lastRunOK"`
	LastMessage string `json:"lastMessage"`

	// BuiltIn sources live in the scraper's code rather than this table —
	// Wikidata and English Heritage, which between them supply nearly
	// everything. Leaving them off the page made it a list of failures.
	BuiltIn bool `json:"builtIn"`
}

// UIAddedNote marks rows added through the web UI. The scraper seeds its
// own candidates with INSERT OR IGNORE keyed on name, so deleting one of
// those just brings it back on the next run; only rows we put here
// ourselves are safe to delete.
const UIAddedNote = "added via the web UI"

// SourceKinds are the extractors the scraper knows. 'auto' probes the URL
// and picks one, which is the right default for a site nobody has looked
// at yet — and it tries 'wpevents' first, because a documented API beats
// every kind of scraping.
var SourceKinds = []string{"auto", "wpevents", "browser", "ical", "jsonld", "sitemap"}

// refusedHosts are sites this form should not queue an attempt at. The
// National Trust is already covered by a source written in code, which
// reads a property's events page and stops if the site answers with a
// bot-protection challenge; adding it here would either duplicate that or,
// with the browser kind, point a renderer at a challenge — which would be
// working around an access control rather than reading a page.
var refusedHosts = map[string]string{
	"nationaltrust.org.uk": "National Trust events are already collected by " +
		"the built-in source, and its properties come from Wikidata — there " +
		"is nothing to add here.",
}

var nameCleanRe = regexp.MustCompile(`[^a-z0-9]+`)

// ErrSourceExists is returned when the URL is already in the table.
var ErrSourceExists = errors.New("that site is already in the list")

func sourceTimestamp() string {
	// Matches the scraper's format so one convention holds in this table.
	return time.Now().UTC().Format("2006-01-02T15:04:05.000000Z")
}

// CodeSources are the sources written in Python rather than held in the
// sources table, so they have no row to join to and are still real.
//
// Kept in step with scraper/daysout_scraper/sources/__init__.py by a test:
// a name missing from here would be treated as leftover history and hidden
// from the Sources tab the moment its row was gone.
var CodeSources = []string{
	"wikidata", "english_heritage", "national_trust", "historic-houses",
	"shuttleworth-events",
}

// sourcesQuery lists every source the scraper has, with what each one is
// contributing.
//
// The name set is the union of the sources table and whatever has actually
// run or produced rows, because the sources written in code — Wikidata and
// English Heritage — are not in the table and are the two that work. A
// page listing only the table was a list of things that had failed.
//
// A source that was removed stays gone: its scrape_runs history would
// otherwise bring it back through the union, and with no row to join to it
// would look built in — listed for ever and impossible to remove again.
//
// Ordered by events contributed, so what is working is at the top.
const sourcesQuery = `
WITH names AS (
    SELECT name AS name FROM sources
    UNION SELECT source FROM scrape_runs WHERE source != 'seed'
    UNION SELECT source FROM events WHERE source != 'seed'
)
SELECT n.name,
       COALESCE(s.url, ''), COALESCE(s.kind, ''), COALESCE(s.category, ''),
       COALESCE(s.enabled, 1), COALESCE(s.notes, ''), COALESCE(s.added, ''),
       COALESCE(s.last_status, ''),
       COALESCE(s.venue_name, ''), COALESCE(s.venue_postcode, ''),
       s.name IS NULL AS built_in,
       (SELECT COUNT(*) FROM events e WHERE e.source = n.name),
       (SELECT COUNT(*) FROM destinations d WHERE d.source = n.name),
       (SELECT r.started_at FROM scrape_runs r
          WHERE r.source = n.name ORDER BY r.id DESC LIMIT 1),
       (SELECT r.ok FROM scrape_runs r
          WHERE r.source = n.name ORDER BY r.id DESC LIMIT 1),
       (SELECT r.message FROM scrape_runs r
          WHERE r.source = n.name ORDER BY r.id DESC LIMIT 1)
FROM names n LEFT JOIN sources s ON s.name = n.name
WHERE n.name NOT IN (SELECT name FROM removed_sources)
ORDER BY 12 DESC, 13 DESC, n.name`

// Sources returns every source with what it is contributing, for the UI.
func (s *Store) Sources() ([]Source, error) {

	rows, err := s.DB.Query(sourcesQuery)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []Source{}
	for rows.Next() {
		var src Source
		var enabled, builtIn int
		// A source that has never finished a run has no outcome to report.
		var lastRun, lastMessage sql.NullString
		var lastOK sql.NullBool

		if err := rows.Scan(&src.Name, &src.URL, &src.Kind, &src.Category,
			&enabled, &src.Notes, &src.Added, &src.LastStatus,
			&src.VenueName, &src.VenuePostcode, &builtIn,
			&src.Events, &src.Destinations,
			&lastRun, &lastOK, &lastMessage); err != nil {
			return nil, err
		}
		src.Enabled = enabled != 0
		src.BuiltIn = builtIn != 0

		// A name with no row that no code source claims is leftover
		// history, not a source. Listing it showed a source that could
		// not be scraped (the scraper has nothing to run), could not be
		// updated, and could not be removed because it looked built in.
		if src.BuiltIn && !slices.Contains(CodeSources, src.Name) {
			continue
		}
		src.UserAdded = strings.HasPrefix(src.Notes, UIAddedNote)
		src.LastRun = lastRun.String
		src.LastRunOK = lastOK.Valid && lastOK.Bool
		src.LastMessage = lastMessage.String
		result = append(result, src)
	}
	return result, rows.Err()
}

// normaliseSourceURL validates a URL typed by a person and returns it in a
// canonical form. Being lenient about the scheme matters: people paste
// "ngs.org.uk/find-a-garden" as often as they paste a full URL.
func normaliseSourceURL(raw string) (string, error) {

	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", errors.New("enter the address of a website")
	}
	if !strings.Contains(raw, "://") {
		raw = "https://" + raw
	}

	parsed, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("that doesn't look like a web address: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", errors.New("only http and https addresses can be scraped")
	}
	host := strings.ToLower(parsed.Hostname())
	if !strings.Contains(host, ".") {
		return "", errors.New("that doesn't look like a web address")
	}
	for refused, reason := range refusedHosts {
		if host == refused || strings.HasSuffix(host, "."+refused) {
			return "", errors.New(reason)
		}
	}
	// Lower-case Host, not Hostname: the latter drops the port, which
	// silently rewrote http://host:8123/events to http://host/events and
	// sent the scraper somewhere nothing was listening.
	parsed.Host = strings.ToLower(parsed.Host)
	parsed.Fragment = ""
	return parsed.String(), nil
}

// sourceName derives a short stable name from the URL — "ngs.org.uk" plus
// the first path segment — and makes it unique, since name is the key the
// scraper and its run log use.
func (s *Store) sourceName(parsed *url.URL) (string, error) {

	host := strings.TrimPrefix(parsed.Hostname(), "www.")
	base := strings.TrimSuffix(host, ".co.uk")
	base = strings.TrimSuffix(base, ".org.uk")
	base = strings.TrimSuffix(base, ".com")
	base = strings.TrimSuffix(base, ".org")

	if segment := strings.Trim(parsed.Path, "/"); segment != "" {
		if i := strings.Index(segment, "/"); i > 0 {
			segment = segment[:i]
		}
		base += "-" + segment
	}
	base = strings.Trim(nameCleanRe.ReplaceAllString(strings.ToLower(base), "-"), "-")
	if base == "" {
		base = "source"
	}
	if len(base) > 60 {
		base = base[:60]
	}

	name := base
	for attempt := 2; attempt < 100; attempt++ {
		var exists int
		err := s.DB.QueryRow(
			`SELECT COUNT(*) FROM sources WHERE name = ?`, name).Scan(&exists)
		if err != nil {
			return "", err
		}
		if exists == 0 {
			return name, nil
		}
		name = fmt.Sprintf("%s-%d", base, attempt)
	}
	return "", errors.New("too many sources with that name")
}

// AddSource records a site for the scraper to visit on its next run.
//
// It does not fetch anything: the server never touches the internet (that
// is the whole design), so a new row is a request, not a result. The
// scraper probes it, records what it found in last_status, and the UI
// shows that back.
func (s *Store) AddSource(rawURL, category, kind, venueName, venuePostcode string) (Source, error) {

	normalised, err := normaliseSourceURL(rawURL)
	if err != nil {
		return Source{}, err
	}
	parsed, err := url.Parse(normalised)
	if err != nil {
		return Source{}, err
	}
	if kind == "" {
		kind = "auto"
	}
	if !slices.Contains(SourceKinds, kind) {
		return Source{}, fmt.Errorf("unknown kind %q", kind)
	}

	var existing string
	err = s.DB.QueryRow(`SELECT name FROM sources WHERE url = ?`, normalised).Scan(&existing)
	if err == nil {
		return Source{}, fmt.Errorf("%w (as %q)", ErrSourceExists, existing)
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return Source{}, err
	}

	name, err := s.sourceName(parsed)
	if err != nil {
		return Source{}, err
	}

	added := sourceTimestamp()
	notes := UIAddedNote
	venuePostcode = strings.ToUpper(strings.TrimSpace(venuePostcode))
	venueName = strings.TrimSpace(venueName)
	if _, err := s.DB.Exec(
		`INSERT INTO sources (name, url, kind, category, enabled, notes, added,
		     venue_name, venue_postcode)
		 VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)`,
		name, normalised, kind, category, notes, added,
		venueName, venuePostcode); err != nil {
		return Source{}, err
	}

	return Source{Name: name, URL: normalised, Kind: kind, Category: category,
		Enabled: true, Notes: notes, Added: added, UserAdded: true,
		VenueName: venueName, VenuePostcode: venuePostcode}, nil
}

// DeleteSource removes a source and remembers that it was removed.
//
// Without the record the scraper would re-insert any candidate missing
// from the table on its next run, so a removal would quietly undo itself.
// Sources written in code have no row here and cannot be removed.
//
// The events it contributed go with it: nothing refreshes them once the
// source is gone, so they could never be corrected or aged out. Its venues
// go too, unless another source's events are held there.
func (s *Store) DeleteSource(name string) error {

	result, err := s.DB.Exec(`DELETE FROM sources WHERE name = ?`, name)
	if err != nil {
		return err
	}
	if rows, _ := result.RowsAffected(); rows == 0 {
		return fmt.Errorf("no source named %q (sources built into the "+
			"scraper cannot be removed)", name)
	}

	// Its events go too. Nothing refreshes them once the source is gone,
	// so leaving them would put rows on the map that can never be
	// corrected or aged out.
	if _, err := s.DB.Exec(`DELETE FROM events WHERE source = ?`, name); err != nil {
		return err
	}
	// Its venues go only if nothing else is using them: another source's
	// event may sit at a venue this one created, and destinations cascade
	// to their events, so a careless delete here would take those with it.
	if _, err := s.DB.Exec(
		`DELETE FROM destinations WHERE source = ?
		   AND id NOT IN (SELECT destination_id FROM events)`, name); err != nil {
		return err
	}

	_, err = s.DB.Exec(
		`INSERT OR REPLACE INTO removed_sources (name, removed_at) VALUES (?, ?)`,
		name, sourceTimestamp())
	return err
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
