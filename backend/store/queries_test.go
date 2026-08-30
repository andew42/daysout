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

	result, err := s.Events(51.50, -2.20, 180, 7, nil)
	if err != nil {
		t.Fatal(err)
	}
	events := result.Events
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

func TestEventsSayWhyOthersAreMissing(t *testing.T) {

	s := newTestStore(t)
	today := time.Now().Format("2006-01-02")
	nextMonth := time.Now().AddDate(0, 0, 40).Format("2006-01-02")

	// Near enough and soon: shown.
	addDestination(t, s, "Near Hall", 51.50, -2.20)
	addEvent(t, s, "Near Hall", "Village fete", today, today)

	// Real, but an hour and a half away — the case that had a source
	// reporting five events on the Sources page and none here.
	addDestination(t, s, "Stonor Park", 51.57, -0.95)
	addEvent(t, s, "Stonor Park", "Chilterns craft fair", today, today)

	// Near enough, but beyond the look-ahead.
	addEvent(t, s, "Near Hall", "Autumn fair", nextMonth, nextMonth)

	result, err := s.Events(51.50, -2.20, 60, 7, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Events) != 1 || result.Events[0].Title != "Village fete" {
		t.Fatalf("shown = %+v, want just the near, soon one", result.Events)
	}
	if result.Excluded.TooFar != 1 {
		t.Errorf("tooFar = %d, want 1", result.Excluded.TooFar)
	}
	if result.Excluded.NearestName != "Stonor Park" {
		t.Errorf("nearestName = %q, want the closest one that missed out",
			result.Excluded.NearestName)
	}
	if result.Excluded.NearestMinutes <= 60 {
		t.Errorf("nearestMinutes = %.0f, want more than the 60 limit",
			result.Excluded.NearestMinutes)
	}
	if result.Excluded.Later != 1 {
		t.Errorf("later = %d, want 1", result.Excluded.Later)
	}
}

func TestAnEventsOwnCategoryCounts(t *testing.T) {

	// A craft fair at a historic house is both. Hiding it because the
	// house is not ticked would be wrong.
	s := newTestStore(t)
	today := time.Now().Format("2006-01-02")
	addDestination(t, s, "Old Hall", 51.50, -2.20) // category historic-house
	addEvent(t, s, "Old Hall", "Craft fair", today, today)
	if _, err := s.DB.Exec(
		`UPDATE events SET category = 'craft' WHERE title = 'Craft fair'`); err != nil {
		t.Fatal(err)
	}

	result, err := s.Events(51.50, -2.20, 60, 7, []string{"craft"})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Events) != 1 {
		t.Fatalf("got %d events, want the craft fair kept by its own category",
			len(result.Events))
	}

	// And a category matching neither still excludes it, with a reason.
	result, err = s.Events(51.50, -2.20, 60, 7, []string{"airfield"})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Events) != 0 || result.Excluded.WrongCategory != 1 {
		t.Errorf("got %d events, wrongCategory=%d; want 0 and 1",
			len(result.Events), result.Excluded.WrongCategory)
	}
}
