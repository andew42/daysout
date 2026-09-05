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

// Sources used to be rows. A database from that era still has the tables,
// and leaving them behind would mean a schema that describes a feature
// nothing implements — so the migration drops them, and must do it
// without disturbing anything else in the file.
func TestMigrateDropsTheSourcesTables(t *testing.T) {

	dir := t.TempDir()

	first, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := first.DB.Exec(
		`CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
		 CREATE TABLE removed_sources (name TEXT PRIMARY KEY, removed_at TEXT);
		 INSERT INTO sources (name) VALUES ('a-listing-site');
		 INSERT INTO removed_sources VALUES ('gone', '2026-01-01')`); err != nil {
		t.Fatalf("could not simulate the older schema: %v", err)
	}
	addDestination(t, first, "Old Hall", 51.5, -2.2)
	first.Close()

	second, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()

	for _, table := range droppedTables {
		var name string
		if err := second.DB.QueryRow(
			`SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?`,
			table).Scan(&name); err == nil {
			t.Errorf("%s is still there", table)
		}
	}

	// Reopening must not fail on tables that have already gone.
	third, err := Open(dir)
	if err != nil {
		t.Fatalf("second migration of an already-migrated database: %v", err)
	}
	defer third.Close()

	var destinations int
	if err := third.DB.QueryRow(
		`SELECT COUNT(*) FROM destinations`).Scan(&destinations); err != nil {
		t.Fatal(err)
	}
	if destinations != 1 {
		t.Errorf("destinations = %d, want the row to survive", destinations)
	}
}
