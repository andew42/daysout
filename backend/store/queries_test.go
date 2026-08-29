package store

import (
	"testing"
	"time"
)

func TestIsOngoing(t *testing.T) {

	cases := []struct {
		name, start, end string
		want             bool
	}{
		{"one-day joust", "2026-08-29", "2026-08-29", false},
		{"bank holiday weekend", "2026-08-29", "2026-08-31", false},
		{"two-week trail", "2026-08-01", "2026-08-15", false},
		{"standing knitting group", "2026-01-20", "2026-10-27", true},
		{"tours spanning a year", "2025-03-27", "2026-12-04", true},
		{"unparseable dates are not ongoing", "soon", "later", false},
	}
	for _, c := range cases {
		if got := isOngoing(c.start, c.end); got != c.want {
			t.Errorf("%s: isOngoing(%q, %q) = %v, want %v", c.name, c.start, c.end, got, c.want)
		}
	}
}

func TestEventsPutSpecialBeforeOngoing(t *testing.T) {

	s := newTestStore(t)
	today := time.Now().Format("2006-01-02")
	soon := time.Now().AddDate(0, 0, 2).Format("2006-01-02")
	farOff := time.Now().AddDate(0, 6, 0).Format("2006-01-02")
	longAgo := time.Now().AddDate(0, -6, 0).Format("2006-01-02")

	// The ongoing one is nearer, so only the special-first rule can put the
	// joust on top.
	addDestination(t, s, "Near Hall", 51.50, -2.20)
	addDestination(t, s, "Far Castle", 51.90, -2.60)
	addEvent(t, s, "Near Hall", "Knitting Group", longAgo, farOff)
	addEvent(t, s, "Far Castle", "Legendary Joust", today, soon)

	events, err := s.Events(51.50, -2.20, 180, 7, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(events) != 2 {
		t.Fatalf("got %d events, want 2", len(events))
	}
	if events[0].Title != "Legendary Joust" || events[0].Ongoing {
		t.Errorf("first event = %q (ongoing=%v), want the special one first",
			events[0].Title, events[0].Ongoing)
	}
	if !events[1].Ongoing {
		t.Errorf("second event %q should be flagged ongoing", events[1].Title)
	}
}
