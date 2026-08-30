package store

import (
	"errors"
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
		source, err := s.AddSource(tc.typed, "craft", "")
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
		if _, err := s.AddSource(tc.typed, "garden", ""); err == nil {
			t.Errorf("AddSource(%q) succeeded, want a refusal", tc.typed)
		} else if !strings.Contains(err.Error(), tc.wantInErr) {
			t.Errorf("AddSource(%q) error = %q, want it to mention %q",
				tc.typed, err, tc.wantInErr)
		}
	}
}

func TestAddSourceRejectsAnUnknownKind(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://example.org/", "art", "telepathy"); err == nil {
		t.Error("an unknown extractor kind should be refused, not stored")
	}
}

func TestAddSourceIsNotSilentlyDuplicated(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://example.org/events", "music", ""); err != nil {
		t.Fatal(err)
	}
	// Same site, typed without the scheme — still the same site.
	_, err := s.AddSource("example.org/events", "music", "")
	if !errors.Is(err, ErrSourceExists) {
		t.Fatalf("second add error = %v, want ErrSourceExists", err)
	}
}

func TestNamesStayUniqueWhenTheyCollide(t *testing.T) {

	s := newTestStore(t)
	first, err := s.AddSource("https://example.org/events", "music", "")
	if err != nil {
		t.Fatal(err)
	}
	// Different URL, same derived name.
	second, err := s.AddSource("https://example.org/events/2027", "music", "")
	if err != nil {
		t.Fatal(err)
	}
	if first.Name == second.Name {
		t.Fatalf("both sources are named %q; name is the scraper's key", first.Name)
	}
}

func TestDeleteOnlyRemovesSourcesAddedHere(t *testing.T) {

	s := newTestStore(t)
	added, err := s.AddSource("https://example.org/events", "music", "")
	if err != nil {
		t.Fatal(err)
	}
	if err := s.DeleteSource(added.Name); err != nil {
		t.Fatalf("deleting a source added here: %v", err)
	}

	// A seeded candidate, as the scraper writes it. Deleting one is
	// pointless — the next scrape re-inserts it — so it must be refused
	// with an explanation rather than appearing to work.
	if _, err := s.DB.Exec(
		`INSERT INTO sources (name, url, kind, category, enabled, notes, added)
		 VALUES ('seeded', 'https://seeded.example/', 'auto', 'garden',
		         1, 'a candidate from the scraper', '2026-01-01')`); err != nil {
		t.Fatal(err)
	}
	err = s.DeleteSource("seeded")
	if err == nil {
		t.Fatal("deleting a seeded candidate should be refused")
	}
	if !strings.Contains(err.Error(), "disable") {
		t.Errorf("error = %q, want it to point at disabling instead", err)
	}
}

func TestSourcesListsWhatTheScraperRecorded(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.AddSource("https://example.org/events", "music", "browser"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.DB.Exec(
		`UPDATE sources SET last_status = 'sitemap' WHERE name = 'example-events'`); err != nil {
		t.Fatal(err)
	}
	if err := s.SetSourceEnabled("example-events", false); err != nil {
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
	if sources[0].Enabled {
		t.Error("source should be disabled after SetSourceEnabled(false)")
	}
	if sources[0].Kind != "browser" {
		t.Errorf("kind = %q, want the kind it was added with", sources[0].Kind)
	}
}
