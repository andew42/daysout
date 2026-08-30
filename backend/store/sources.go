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
	Name       string `json:"name"`
	URL        string `json:"url"`
	Kind       string `json:"kind"`
	Category   string `json:"category"`
	Enabled    bool   `json:"enabled"`
	Notes      string `json:"notes"`
	Added      string `json:"added"`
	LastStatus string `json:"lastStatus"`
	// UserAdded rows may be deleted; seeded ones may only be disabled,
	// because the scraper re-inserts any candidate missing from the table.
	UserAdded bool `json:"userAdded"`
}

// UIAddedNote marks rows added through the web UI. The scraper seeds its
// own candidates with INSERT OR IGNORE keyed on name, so deleting one of
// those just brings it back on the next run; only rows we put here
// ourselves are safe to delete.
const UIAddedNote = "added via the web UI"

// SourceKinds are the extractors the scraper knows. 'auto' probes the URL
// and picks one, which is the right default for a site nobody has looked
// at yet.
var SourceKinds = []string{"auto", "browser", "ical", "jsonld", "sitemap"}

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

// Sources returns every row, newest first, for the UI list.
func (s *Store) Sources() ([]Source, error) {

	rows, err := s.DB.Query(
		`SELECT name, url, kind, category, enabled, notes, added, last_status
		 FROM sources ORDER BY added DESC, name`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []Source{}
	for rows.Next() {
		var src Source
		var enabled int
		if err := rows.Scan(&src.Name, &src.URL, &src.Kind, &src.Category,
			&enabled, &src.Notes, &src.Added, &src.LastStatus); err != nil {
			return nil, err
		}
		src.Enabled = enabled != 0
		src.UserAdded = strings.HasPrefix(src.Notes, UIAddedNote)
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
	parsed.Host = host
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
func (s *Store) AddSource(rawURL, category, kind string) (Source, error) {

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
	if _, err := s.DB.Exec(
		`INSERT INTO sources (name, url, kind, category, enabled, notes, added)
		 VALUES (?, ?, ?, ?, 1, ?, ?)`,
		name, normalised, kind, category, notes, added); err != nil {
		return Source{}, err
	}

	return Source{Name: name, URL: normalised, Kind: kind, Category: category,
		Enabled: true, Notes: notes, Added: added, UserAdded: true}, nil
}

// SetSourceEnabled turns a source on or off for future scrapes.
func (s *Store) SetSourceEnabled(name string, enabled bool) error {

	value := 0
	if enabled {
		value = 1
	}
	result, err := s.DB.Exec(
		`UPDATE sources SET enabled = ? WHERE name = ?`, value, name)
	if err != nil {
		return err
	}
	if rows, _ := result.RowsAffected(); rows == 0 {
		return fmt.Errorf("no source named %q", name)
	}
	return nil
}

// DeleteSource removes a source added through the UI. Seeded candidates
// are refused rather than silently reappearing at the next scrape, which
// re-inserts anything missing from the table; disable those instead.
//
// Destinations and events an enabled source already contributed stay
// where they are — nothing here deletes data the map is showing.
func (s *Store) DeleteSource(name string) error {

	var notes string
	err := s.DB.QueryRow(`SELECT notes FROM sources WHERE name = ?`, name).Scan(&notes)
	if errors.Is(err, sql.ErrNoRows) {
		return fmt.Errorf("no source named %q", name)
	}
	if err != nil {
		return err
	}
	if !strings.HasPrefix(notes, UIAddedNote) {
		return errors.New("that source is one of the built-in candidates — " +
			"disable it instead, or the scraper will add it back")
	}
	_, err = s.DB.Exec(`DELETE FROM sources WHERE name = ?`, name)
	return err
}
