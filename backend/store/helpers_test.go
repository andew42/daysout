package store

import (
	"testing"
	"time"
)

// newTestStore returns a Store backed by a fresh database in t.TempDir().
func newTestStore(t *testing.T) *Store {

	t.Helper()
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func addDestination(t *testing.T, s *Store, name string, lat, lon float64) {

	t.Helper()
	now := time.Now().Format(time.RFC3339)
	_, err := s.DB.Exec(
		`INSERT INTO destinations
		   (name, category, lat, lon, source, source_id, first_seen, last_seen)
		 VALUES (?, 'historic-house', ?, ?, 'test', ?, ?, ?)`,
		name, lat, lon, name, now, now)
	if err != nil {
		t.Fatal(err)
	}
}

func addEvent(t *testing.T, s *Store, destination, title, startDate, endDate string) {

	t.Helper()
	now := time.Now().Format(time.RFC3339)
	_, err := s.DB.Exec(
		`INSERT INTO events
		   (destination_id, title, start_date, end_date, source, source_id, last_seen)
		 SELECT id, ?, ?, ?, 'test', ?, ? FROM destinations WHERE name = ?`,
		title, startDate, endDate, title, now, destination)
	if err != nil {
		t.Fatal(err)
	}
}
