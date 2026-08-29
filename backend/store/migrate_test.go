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
