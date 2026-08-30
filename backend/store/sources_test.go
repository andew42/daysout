package store

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"testing"
)

func TestAddSourceAcceptsWhatPeopleActuallyType(t *testing.T) {

	cases := []struct {
		typed    string
		wantURL  string
		wantName string
	}{
		// A bare host: the common case when pasting from a browser bar.
		{"ngs.org.uk", "https://ngs.org.uk", "ngs"},
		{"https://www.example-fairs.co.uk/whats-on/2026",
			"https://www.example-fairs.co.uk/whats-on/2026", "example-fairs-whats-on"},
		// Surrounding whitespace and a fragment are noise, not intent.
		{"  https://shows.example.com/list#top  ",
			"https://shows.example.com/list", "shows-example-list"},
		// A port is part of the address. Dropping it sent the scraper to
		// port 80, where nothing was listening.
		{"http://192.168.1.10:8123/events",
			"http://192.168.1.10:8123/events", "192-168-1-10-events"},
	}

	for _, tc := range cases {
		s := newTestStore(t)
		source, err := s.AddSource(tc.typed, "craft", "", "", "")
		if err != nil {
			t.Fatalf("AddSource(%q): %v", tc.typed, err)
		}
		if source.URL != tc.wantURL {
			t.Errorf("AddSource(%q) URL = %q, want %q", tc.typed, source.URL, tc.wantURL)
		}
		if source.Name != tc.wantName {
			t.Errorf("AddSource(%q) name = %q, want %q", tc.typed, source.Name, tc.wantName)
		}
		if source.Kind != "auto" {
			t.Errorf("kind = %q, want auto (probe and pick) by default", source.Kind)
		}
		if !source.Enabled || !source.UserAdded {
			t.Errorf("a source added here should be enabled and user-added: %+v", source)
		}
	}
}

func TestAddSourceRejectsWhatCannotBeScraped(t *testing.T) {

	cases := []struct {
		typed     string
		wantInErr string
	}{
		{"", "enter the address"},
		{"not a url at all", "web address"},
		{"ftp://files.example.com/list", "http"},
		// Already covered by a source written in code — and adding it with
		// the browser kind would point a renderer at a site that answers
		// automated clients with a challenge.
		{"https://www.nationaltrust.org.uk/visit", "built-in source"},
		{"nationaltrust.org.uk", "built-in source"},
	}

	for _, tc := range cases {
		s := newTestStore(t)
		if _, err := s.AddSource(tc.typed, "garden", "", "", ""); err == nil {
			t.Errorf("AddSource(%q) succeeded, want a refusal", tc.typed)
		} else if !strings.Contains(err.Error(), tc.wantInErr) {
			t.Errorf("AddSource(%q) error = %q, want it to mention %q",
				tc.typed, err, tc.wantInErr)
		}
	}
}

func TestAddSourceRejectsAnUnknownKind(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://example.org/", "art", "telepathy", "", ""); err == nil {
		t.Error("an unknown extractor kind should be refused, not stored")
	}
}

func TestAddSourceIsNotSilentlyDuplicated(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://example.org/events", "music", "", "", ""); err != nil {
		t.Fatal(err)
	}
	// Same site, typed without the scheme — still the same site.
	_, err := s.AddSource("example.org/events", "music", "", "", "")
	if !errors.Is(err, ErrSourceExists) {
		t.Fatalf("second add error = %v, want ErrSourceExists", err)
	}
}

func TestNamesStayUniqueWhenTheyCollide(t *testing.T) {

	s := newTestStore(t)
	first, err := s.AddSource("https://example.org/events", "music", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	// Different URL, same derived name.
	second, err := s.AddSource("https://example.org/events/2027", "music", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if first.Name == second.Name {
		t.Fatalf("both sources are named %q; name is the scraper's key", first.Name)
	}
}

func TestRemovalIsRememberedSoItStays(t *testing.T) {

	s := newTestStore(t)
	added, err := s.AddSource("https://example.org/events", "music", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if err := s.DeleteSource(added.Name); err != nil {
		t.Fatalf("removing a source: %v", err)
	}

	// The scraper re-inserts any candidate missing from the table, so a
	// removal that is not recorded quietly undoes itself on the next run.
	var recorded int
	if err := s.DB.QueryRow(
		`SELECT COUNT(*) FROM removed_sources WHERE name = ?`,
		added.Name).Scan(&recorded); err != nil {
		t.Fatal(err)
	}
	if recorded != 1 {
		t.Error("a removed source should be recorded, or the scraper adds it back")
	}
}

func TestSeededCandidatesCanAlsoBeRemoved(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.DB.Exec(
		`INSERT INTO sources (name, url, kind, category, enabled, notes, added)
		 VALUES ('seeded', 'https://seeded.example/', 'auto', 'garden',
		         1, 'a candidate from the scraper', '2026-01-01')`); err != nil {
		t.Fatal(err)
	}
	if err := s.DeleteSource("seeded"); err != nil {
		t.Fatalf("a seeded candidate should be removable now: %v", err)
	}
}

func TestABuiltInSourceCannotBeRemoved(t *testing.T) {

	// Wikidata and English Heritage live in the scraper's code and have no
	// row here, so there is nothing to remove and saying so is kinder than
	// appearing to succeed.
	s := newTestStore(t)
	err := s.DeleteSource("english_heritage")
	if err == nil {
		t.Fatal("removing a built-in source should be refused")
	}
	if !strings.Contains(err.Error(), "built into the scraper") {
		t.Errorf("error = %q, want it to explain why", err)
	}
}

func TestSourcesListsWhatTheScraperRecorded(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://example.org/events", "music", "browser", "", ""); err != nil {
		t.Fatal(err)
	}
	if _, err := s.DB.Exec(
		`UPDATE sources SET last_status = 'sitemap' WHERE name = 'example-events'`); err != nil {
		t.Fatal(err)
	}
	sources, err := s.Sources()
	if err != nil {
		t.Fatal(err)
	}
	if len(sources) != 1 {
		t.Fatalf("got %d sources, want 1", len(sources))
	}
	if sources[0].LastStatus != "sitemap" {
		t.Errorf("lastStatus = %q, want the scraper's verdict", sources[0].LastStatus)
	}
	if sources[0].Kind != "browser" {
		t.Errorf("kind = %q, want the kind it was added with", sources[0].Kind)
	}
}

// seedRun records a scrape run and some rows for a source, as the scraper
// would, so the listing has something to count.
func seedRun(t *testing.T, s *Store, name string, ok bool, message string,
	events int) {

	t.Helper()
	if _, err := s.DB.Exec(
		`INSERT INTO scrape_runs (source, started_at, finished_at, ok, message)
		 VALUES (?, '2026-08-30T12:00:00Z', '2026-08-30T12:01:00Z', ?, ?)`,
		name, ok, message); err != nil {
		t.Fatal(err)
	}
	if _, err := s.DB.Exec(
		`INSERT INTO destinations (name, category, lat, lon, source, source_id,
		     first_seen, last_seen)
		 VALUES (?, 'garden', 51.0, -2.0, ?, ?, '2026-01-01', '2026-01-01')`,
		name+" venue", name, name+"-venue"); err != nil {
		t.Fatal(err)
	}
	var destinationID int
	if err := s.DB.QueryRow(
		`SELECT id FROM destinations WHERE source = ?`, name).Scan(&destinationID); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < events; i++ {
		if _, err := s.DB.Exec(
			`INSERT INTO events (destination_id, title, start_date, end_date,
			     source, source_id, last_seen)
			 VALUES (?, ?, '2026-09-05', '2026-09-05', ?, ?, '2026-01-01')`,
			destinationID, fmt.Sprintf("Event %d", i), name,
			fmt.Sprintf("%s-%d", name, i)); err != nil {
			t.Fatal(err)
		}
	}
}

func TestSourcesReportWhatEachIsContributing(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://quiet.example.org/", "craft", "", "", ""); err != nil {
		t.Fatal(err)
	}
	seedRun(t, s, "quiet-example", false, "no places found", 0)

	// A source written in code: not a row in the table, and the one doing
	// the work. Leaving it off the page made it a list of failures.
	seedRun(t, s, "english_heritage", true, "392 places, 116/116 events linked", 3)

	sources, err := s.Sources()
	if err != nil {
		t.Fatal(err)
	}
	if len(sources) != 2 {
		t.Fatalf("got %d sources, want the table row and the built-in one", len(sources))
	}

	// Most events first: what is working belongs at the top.
	if sources[0].Name != "english_heritage" {
		t.Errorf("first source = %q, want the one contributing events", sources[0].Name)
	}
	if sources[0].Events != 3 || sources[0].Destinations != 1 {
		t.Errorf("counts = %d events, %d places; want 3 and 1",
			sources[0].Events, sources[0].Destinations)
	}
	if !sources[0].BuiltIn {
		t.Error("a source with no row in the table is built in")
	}
	if !sources[0].LastRunOK || sources[0].LastMessage != "392 places, 116/116 events linked" {
		t.Errorf("last run = %v %q, want the scraper's own message",
			sources[0].LastRunOK, sources[0].LastMessage)
	}

	if sources[1].Name != "quiet-example" {
		t.Fatalf("second source = %q", sources[1].Name)
	}
	if sources[1].Events != 0 {
		t.Errorf("a source that found nothing should report 0 events, got %d",
			sources[1].Events)
	}
	if sources[1].BuiltIn {
		t.Error("a row added through the UI is not built in")
	}
	if sources[1].LastRunOK {
		t.Error("last run failed, so lastRunOK should be false")
	}
}

func TestASourceThatHasNeverRunReportsNoOutcome(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://new.example.org/", "craft", "", "", ""); err != nil {
		t.Fatal(err)
	}
	sources, err := s.Sources()
	if err != nil {
		t.Fatal(err)
	}
	if len(sources) != 1 {
		t.Fatalf("got %d sources, want 1", len(sources))
	}
	// Null columns must not become a confident-looking "failed".
	if sources[0].LastRun != "" || sources[0].LastMessage != "" || sources[0].LastRunOK {
		t.Errorf("a source never run should report no outcome, got %+v", sources[0])
	}
}

func TestARemovedSourceStaysGone(t *testing.T) {

	s := newTestStore(t)
	added, err := s.AddSource("https://example.org/events", "music", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	// It has run, so it has history — which is what brought it back.
	seedRun(t, s, added.Name, false, "no places found", 0)

	if err := s.DeleteSource(added.Name); err != nil {
		t.Fatal(err)
	}
	sources, err := s.Sources()
	if err != nil {
		t.Fatal(err)
	}
	for _, source := range sources {
		if source.Name == added.Name {
			t.Fatalf("a removed source came back through its run history, "+
				"as builtIn=%v — listed for ever and impossible to remove again",
				source.BuiltIn)
		}
	}
}

func TestRemovingASourceTakesItsEventsWithIt(t *testing.T) {

	s := newTestStore(t)
	added, err := s.AddSource("https://example.org/events", "music", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	seedRun(t, s, added.Name, true, "1 places, 2/2 events linked", 2)

	if err := s.DeleteSource(added.Name); err != nil {
		t.Fatal(err)
	}
	// Nothing refreshes them once the source is gone, so rows left behind
	// could never be corrected or aged out.
	var events, destinations int
	if err := s.DB.QueryRow(`SELECT COUNT(*) FROM events WHERE source = ?`,
		added.Name).Scan(&events); err != nil {
		t.Fatal(err)
	}
	if err := s.DB.QueryRow(`SELECT COUNT(*) FROM destinations WHERE source = ?`,
		added.Name).Scan(&destinations); err != nil {
		t.Fatal(err)
	}
	if events != 0 || destinations != 0 {
		t.Errorf("after removal: %d events and %d places left behind",
			events, destinations)
	}
}

func TestRemovingASourceKeepsAVenueAnotherSourceIsUsing(t *testing.T) {

	s := newTestStore(t)
	added, err := s.AddSource("https://example.org/events", "music", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	seedRun(t, s, added.Name, true, "1 places, 1/1 events linked", 1)

	// Another source's event, held at the venue this one created.
	var venueID int
	if err := s.DB.QueryRow(`SELECT id FROM destinations WHERE source = ?`,
		added.Name).Scan(&venueID); err != nil {
		t.Fatal(err)
	}
	if _, err := s.DB.Exec(
		`INSERT INTO events (destination_id, title, start_date, end_date,
		     source, source_id, last_seen)
		 VALUES (?, 'Someone else''s event', '2026-09-05', '2026-09-05',
		         'other', 'x', '2026-01-01')`, venueID); err != nil {
		t.Fatal(err)
	}

	if err := s.DeleteSource(added.Name); err != nil {
		t.Fatal(err)
	}
	// Destinations cascade to their events, so deleting this venue would
	// silently take the other source's event with it.
	var survived int
	if err := s.DB.QueryRow(
		`SELECT COUNT(*) FROM events WHERE source = 'other'`).Scan(&survived); err != nil {
		t.Fatal(err)
	}
	if survived != 1 {
		t.Error("another source's event was destroyed by removing this one")
	}
}

func TestContributionListsWhatASourceProduced(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://example.org/events", "music", "", "", ""); err != nil {
		t.Fatal(err)
	}
	seedRun(t, s, "example-events", true, "1 places, 3/3 events linked", 3)

	contribution, err := s.Contribution("example-events")
	if err != nil {
		t.Fatal(err)
	}
	if contribution.EventsTotal != 3 || contribution.DestinationsTotal != 1 {
		t.Fatalf("totals = %d events, %d places; want 3 and 1",
			contribution.EventsTotal, contribution.DestinationsTotal)
	}
	if len(contribution.Events) != 3 {
		t.Fatalf("got %d event rows", len(contribution.Events))
	}
	// A count says a source is working; only the rows say whether what it
	// produced is any good, so each needs its venue and date.
	first := contribution.Events[0]
	if first.Where != "example-events venue" || first.When != "2026-09-05" {
		t.Errorf("event row = %+v, want its venue and date", first)
	}
	if contribution.Destinations[0].Postcode == "" &&
		contribution.Destinations[0].Title == "" {
		t.Error("place rows should carry a name")
	}
}

func TestContributionOfASourceWithNothingIsEmptyNotNull(t *testing.T) {

	// The browser renders these directly; a null would be a crash rather
	// than an empty list.
	s := newTestStore(t)
	contribution, err := s.Contribution("never-heard-of-it")
	if err != nil {
		t.Fatal(err)
	}
	if contribution.Events == nil || contribution.Destinations == nil {
		t.Fatal("empty lists must be empty, not null")
	}
	if contribution.EventsTotal != 0 {
		t.Errorf("eventsTotal = %d, want 0", contribution.EventsTotal)
	}
}

func TestContributionShowsADateRangeWhenThereIsOne(t *testing.T) {

	s := newTestStore(t)
	addDestination(t, s, "A venue", 51, -2)
	if _, err := s.DB.Exec(
		`INSERT INTO events (destination_id, title, start_date, end_date,
		     source, source_id, last_seen)
		 VALUES ((SELECT id FROM destinations LIMIT 1), 'A festival',
		         '2026-09-05', '2026-09-07', 'feed', 'f', '2026-01-01')`); err != nil {
		t.Fatal(err)
	}
	contribution, err := s.Contribution("feed")
	if err != nil {
		t.Fatal(err)
	}
	if contribution.Events[0].When != "2026-09-05 – 2026-09-07" {
		t.Errorf("when = %q, want the range", contribution.Events[0].When)
	}
}

// A user-added source whose row is gone leaves its scrape_runs history
// behind. The union brought that history back as a source with no row,
// which reads as built in: listed for ever, never scraped (the scraper
// has no row to run), and impossible to remove. shuttleworth-events sat
// like that on the live site, reporting a failure from hours earlier —
// until it was given a parser of its own, which is why the ghost here is
// a name no code source claims.
func TestLeftoverHistoryIsNotASource(t *testing.T) {

	store := newTestStore(t)
	if _, err := store.DB.Exec(
		`INSERT INTO scrape_runs (source, started_at, finished_at, ok, message)
		 VALUES ('a-source-that-was-removed', '2026-08-30T17:55:41Z',
		         '2026-08-30T17:55:53Z', 0, 'no places found'),
		        ('english_heritage', '2026-08-30T21:36:41Z',
		         '2026-08-30T21:37:02Z', 1, '392 places')`); err != nil {
		t.Fatal(err)
	}

	sources, err := store.Sources()
	if err != nil {
		t.Fatal(err)
	}
	names := map[string]bool{}
	for _, s := range sources {
		names[s.Name] = true
	}
	if names["a-source-that-was-removed"] {
		t.Error("a name with no row and no code source was listed as a source")
	}
	if !names["english_heritage"] {
		t.Error("a code source has no row either, and must still be listed")
	}
}

// The Go list above and the scraper's registry must agree: a code source
// missing from CodeSources vanishes from the Sources tab the moment its
// table row goes, which is exactly the bug this pair exists to prevent.
func TestCodeSourcesMatchTheScraper(t *testing.T) {

	source, err := os.ReadFile("../../scraper/daysout_scraper/sources/__init__.py")
	if err != nil {
		t.Skipf("scraper not present: %v", err)
	}
	classes := regexp.MustCompile(`IMPLEMENTED = \[([^\]]*)\]`).FindSubmatch(source)
	if classes == nil {
		t.Fatal("sources/__init__.py no longer declares IMPLEMENTED")
	}

	// Each class names itself; read the name off its module instead.
	for _, class := range strings.Split(string(classes[1]), ",") {
		class = strings.TrimSpace(class)
		if class == "" {
			continue
		}
		pattern := regexp.MustCompile(`(?s)class ` + class + `\b.*?name = "([^"]+)"`)
		files, _ := filepath.Glob("../../scraper/daysout_scraper/sources/*.py")
		found := ""
		for _, file := range files {
			body, err := os.ReadFile(file)
			if err != nil {
				continue
			}
			if match := pattern.FindSubmatch(body); match != nil {
				found = string(match[1])
				break
			}
		}
		if found == "" {
			t.Errorf("could not find the source name for %s", class)
			continue
		}
		if !slices.Contains(CodeSources, found) {
			t.Errorf("CodeSources is missing %q (class %s)", found, class)
		}
	}
}
