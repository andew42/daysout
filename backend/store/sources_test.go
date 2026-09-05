package store

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"testing"
)

// Every source the scraper has is listed, whether or not it has ever run.
// The list comes from code now, so an empty database is not an empty page
// — which it would have been when sources were rows.
func TestSourcesListsEveryCodeSource(t *testing.T) {

	s := newTestStore(t)
	sources, err := s.Sources()
	if err != nil {
		t.Fatal(err)
	}
	if len(sources) != len(CodeSources) {
		t.Fatalf("got %d sources, want %d", len(sources), len(CodeSources))
	}
	for _, name := range CodeSources {
		found := slices.ContainsFunc(sources, func(src Source) bool {
			return src.Name == name
		})
		if !found {
			t.Errorf("%q is missing from the listing", name)
		}
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
	seedRun(t, s, "english_heritage", true, "392 places, 116/116 events linked", 3)
	seedRun(t, s, "uk-craft-fairs", false, "no places found", 0)

	sources, err := s.Sources()
	if err != nil {
		t.Fatal(err)
	}

	// Most events first: what is working belongs at the top, and a source
	// reporting nothing is the one worth looking at.
	if sources[0].Name != "english_heritage" {
		t.Errorf("first source = %q, want the one contributing events", sources[0].Name)
	}
	if sources[0].Events != 3 || sources[0].Destinations != 1 {
		t.Errorf("counts = %d events, %d places; want 3 and 1",
			sources[0].Events, sources[0].Destinations)
	}
	if !sources[0].LastRunOK || sources[0].LastMessage != "392 places, 116/116 events linked" {
		t.Errorf("last run = %v %q, want the scraper's own message",
			sources[0].LastRunOK, sources[0].LastMessage)
	}

	quiet := sourceNamed(t, sources, "uk-craft-fairs")
	if quiet.Events != 0 {
		t.Errorf("a source that found nothing should report 0 events, got %d",
			quiet.Events)
	}
	if quiet.LastRunOK {
		t.Error("last run failed, so lastRunOK should be false")
	}
}

func sourceNamed(t *testing.T, sources []Source, name string) Source {
	t.Helper()
	for _, src := range sources {
		if src.Name == name {
			return src
		}
	}
	t.Fatalf("%q is not in the listing", name)
	return Source{}
}

func TestASourceThatHasNeverRunReportsNoOutcome(t *testing.T) {

	s := newTestStore(t)
	sources, err := s.Sources()
	if err != nil {
		t.Fatal(err)
	}
	// No rows at all: null columns must not become a confident-looking
	// "failed" against every source on the page.
	for _, src := range sources {
		if src.LastRun != "" || src.LastMessage != "" || src.LastRunOK {
			t.Errorf("a source never run should report no outcome, got %+v", src)
		}
	}
}

func TestContributionListsWhatASourceProduced(t *testing.T) {

	s := newTestStore(t)
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
