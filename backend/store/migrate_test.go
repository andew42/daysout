package store

import (
	"path/filepath"
	"testing"
)

func TestMigrateAddsColumnAndKeepsData(t *testing.T) {

	dir := t.TempDir()

	// A database from before events.category existed.
	first, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := first.DB.Exec(`ALTER TABLE events DROP COLUMN category`); err != nil {
		t.Fatalf("could not simulate the older schema: %v", err)
	}
	addDestination(t, first, "Old Hall", 51.5, -2.2)
	addEvent(t, first, "Old Hall", "Existing Fete", "2026-09-01", "2026-09-01")
	first.Close()

	// Reopening must add the column without losing the row.
	second, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()

	has, err := hasColumn(second.DB, "events", "category")
	if err != nil {
		t.Fatal(err)
	}
	if !has {
		t.Fatal("events.category was not added")
	}

	var title, category string
	err = second.DB.QueryRow(`SELECT title, category FROM events`).Scan(&title, &category)
	if err != nil {
		t.Fatal(err)
	}
	if title != "Existing Fete" {
		t.Errorf("existing event lost: got title %q", title)
	}
	if category != "" {
		t.Errorf("migrated rows should default to empty category, got %q", category)
	}

	// Migration must be idempotent — Open runs it on every start.
	third, err := Open(dir)
	if err != nil {
		t.Fatalf("second reopen failed: %v", err)
	}
	third.Close()

	if _, err := filepath.Abs(dir); err != nil {
		t.Fatal(err)
	}
}

// The house server's database predates sources.site_url, and the Sources
// query selects it: without the migration every request for the page
// would fail on "no such column" rather than merely losing the link.
func TestMigrateAddsTheSourceSiteURL(t *testing.T) {

	dir := t.TempDir()

	first, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	// Rebuilt rather than ALTER ... DROP COLUMN, which SQLite refuses here:
	// it re-parses the stored CREATE TABLE text, and dropping the last
	// column leaves the comment above it after a trailing comma. This is
	// the truer simulation anyway — the old database had neither.
	if _, err := first.DB.Exec(`
		DROP TABLE sources;
		CREATE TABLE sources (
		    id             INTEGER PRIMARY KEY,
		    name           TEXT NOT NULL UNIQUE,
		    url            TEXT NOT NULL,
		    kind           TEXT NOT NULL DEFAULT 'auto',
		    category       TEXT NOT NULL DEFAULT '',
		    enabled        INTEGER NOT NULL DEFAULT 1,
		    notes          TEXT NOT NULL DEFAULT '',
		    added          TEXT NOT NULL,
		    last_status    TEXT NOT NULL DEFAULT '',
		    venue_name     TEXT NOT NULL DEFAULT '',
		    venue_postcode TEXT NOT NULL DEFAULT ''
		)`); err != nil {
		t.Fatalf("could not simulate the older schema: %v", err)
	}
	if _, err := first.DB.Exec(
		`INSERT INTO sources (name, url, kind, category, enabled, notes, added)
		 VALUES ('iacf-newark', 'https://www.iacf.co.uk/?feed=x', 'ical',
		         'antiques', 1, '', '2026-01-01')`); err != nil {
		t.Fatal(err)
	}
	first.Close()

	second, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()

	has, err := hasColumn(second.DB, "sources", "site_url")
	if err != nil {
		t.Fatal(err)
	}
	if !has {
		t.Fatal("sources.site_url was not added")
	}

	// The page must still list the row, with the feed address as its link
	// until the scraper fills a site_url in.
	sources, err := second.Sources()
	if err != nil {
		t.Fatalf("Sources failed after migration: %v", err)
	}
	found := false
	for _, src := range sources {
		if src.Name != "iacf-newark" {
			continue
		}
		found = true
		if src.SiteURL != "" {
			t.Errorf("migrated row should default to no site url, got %q", src.SiteURL)
		}
		if src.URL != "https://www.iacf.co.uk/?feed=x" {
			t.Errorf("the fetch url was lost: %q", src.URL)
		}
	}
	if !found {
		t.Error("the migrated source is missing from the listing")
	}
}

// A feed row carries both: the address the scraper fetches and the one a
// person should be shown.
func TestSourcesReportTheSiteURLSeparately(t *testing.T) {

	s := newTestStore(t)
	if _, err := s.DB.Exec(
		`INSERT INTO sources (name, url, kind, category, enabled, notes, added,
		                      site_url)
		 VALUES ('iacf-newark', 'https://www.iacf.co.uk/?feed=x', 'ical',
		         'antiques', 1, '', '2026-01-01', 'https://www.iacf.co.uk/')`,
	); err != nil {
		t.Fatal(err)
	}

	sources, err := s.Sources()
	if err != nil {
		t.Fatal(err)
	}
	for _, src := range sources {
		if src.Name == "iacf-newark" {
			if src.SiteURL != "https://www.iacf.co.uk/" {
				t.Errorf("site url: got %q", src.SiteURL)
			}
			if src.URL != "https://www.iacf.co.uk/?feed=x" {
				t.Errorf("fetch url: got %q", src.URL)
			}
			return
		}
	}
	t.Error("the source is missing from the listing")
}
