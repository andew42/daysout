package store

import (
	"fmt"
	"slices"
	"strings"
	"time"
)

// Destination is a place worth visiting, with drive-time fields computed
// against the requested home postcode at query time.
type Destination struct {
	ID             int64   `json:"id"`
	Name           string  `json:"name"`
	Category       string  `json:"category"`
	Description    string  `json:"description"`
	URL            string  `json:"url"`
	Postcode       string  `json:"postcode"`
	Lat            float64 `json:"lat"`
	Lon            float64 `json:"lon"`
	Source         string  `json:"source"`
	DistanceKm     float64 `json:"distanceKm"`
	DriveMinutes   float64 `json:"driveMinutes"`
	UpcomingEvents int     `json:"upcomingEvents"`
}

// OngoingDays separates a special event from a standing offer. Venues
// publish long-running programmes ("Knitting Group", Jan–Oct) through the
// same feeds as one-off events; both are worth listing, but a thing that
// has been running for months is not what you want to see first when
// asking what's on this weekend.
const OngoingDays = 14

// Event is a dated event at a destination.
type Event struct {
	ID          int64       `json:"id"`
	Title       string      `json:"title"`
	Description string      `json:"description"`
	URL         string      `json:"url"`
	StartDate   string      `json:"startDate"`
	EndDate     string      `json:"endDate"`
	Category    string      `json:"category"`
	Ongoing     bool        `json:"ongoing"`
	Destination Destination `json:"destination"`
}

// isOngoing reports whether an event spans more than OngoingDays.
func isOngoing(startDate, endDate string) bool {

	start, err := time.Parse("2006-01-02", startDate)
	if err != nil {
		return false
	}
	end, err := time.Parse("2006-01-02", endDate)
	if err != nil {
		return false
	}
	return end.Sub(start) > OngoingDays*24*time.Hour
}

// SourceStatus is the latest scrape run recorded for one source.
type SourceStatus struct {
	Source     string `json:"source"`
	StartedAt  string `json:"startedAt"`
	FinishedAt string `json:"finishedAt"`
	OK         bool   `json:"ok"`
	Message    string `json:"message"`
}

// NormalisePostcode upper-cases and strips spaces: "sn13 8hn" -> "SN138HN".
func NormalisePostcode(pc string) string {
	return strings.ToUpper(strings.ReplaceAll(strings.TrimSpace(pc), " ", ""))
}

// Geocode resolves a postcode to coordinates. A full postcode matches
// exactly; an outward district ("SN13") resolves to the centroid of its
// postcodes so a partial entry still works.
func (s *Store) Geocode(pc string) (lat, lon float64, err error) {

	norm := NormalisePostcode(pc)
	if norm == "" {
		return 0, 0, fmt.Errorf("empty postcode")
	}

	err = s.DB.QueryRow(
		`SELECT lat, lon FROM postcodes WHERE postcode = ?`, norm).Scan(&lat, &lon)
	if err == nil {
		return lat, lon, nil
	}

	// Outward district: stored postcodes have no spaces and the inward part
	// is always 3 characters, so match prefix + exact total length.
	var n int
	err = s.DB.QueryRow(
		`SELECT AVG(lat), AVG(lon), COUNT(*) FROM postcodes
		 WHERE postcode LIKE ? || '%' AND LENGTH(postcode) = LENGTH(?) + 3`,
		norm, norm).Scan(&lat, &lon, &n)
	if err == nil && n > 0 {
		return lat, lon, nil
	}

	var total int
	if err := s.DB.QueryRow(`SELECT COUNT(*) FROM postcodes`).Scan(&total); err == nil && total == 0 {
		return 0, 0, fmt.Errorf("postcode database is empty — run setup/import-postcodes.sh")
	}
	return 0, 0, fmt.Errorf("postcode %q not found", pc)
}

// Destinations returns destinations within maxMinutes drive of (lat, lon),
// optionally filtered by category, sorted nearest first. The destination
// table is small (thousands of rows) so distance is computed in Go over a
// full scan rather than in SQL.
func (s *Store) Destinations(lat, lon, maxMinutes float64, categories []string) ([]Destination, error) {

	today := time.Now().Format("2006-01-02")
	rows, err := s.DB.Query(
		`SELECT d.id, d.name, d.category, d.description, d.url, d.postcode,
		        d.lat, d.lon, d.source,
		        (SELECT COUNT(*) FROM events e
		         WHERE e.destination_id = d.id AND e.end_date >= ?)
		 FROM destinations d`, today)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []Destination{}
	for rows.Next() {
		var d Destination
		if err := rows.Scan(&d.ID, &d.Name, &d.Category, &d.Description, &d.URL,
			&d.Postcode, &d.Lat, &d.Lon, &d.Source, &d.UpcomingEvents); err != nil {
			return nil, err
		}
		if len(categories) > 0 && !slices.Contains(categories, d.Category) {
			continue
		}
		d.DistanceKm = HaversineKm(lat, lon, d.Lat, d.Lon)
		d.DriveMinutes = DriveMinutes(d.DistanceKm)
		if d.DriveMinutes <= maxMinutes {
			result = append(result, d)
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	slices.SortFunc(result, func(a, b Destination) int {
		switch {
		case a.DriveMinutes < b.DriveMinutes:
			return -1
		case a.DriveMinutes > b.DriveMinutes:
			return 1
		}
		return 0
	})
	return result, nil
}

// Events returns events running some time in the next `days` days at
// destinations within maxMinutes drive, ordered by distance from home.
func (s *Store) Events(lat, lon, maxMinutes float64, days int, categories []string) ([]Event, error) {

	today := time.Now().Format("2006-01-02")
	horizon := time.Now().AddDate(0, 0, days).Format("2006-01-02")

	rows, err := s.DB.Query(
		`SELECT e.id, e.title, e.description, e.url, e.start_date, e.end_date,
		        e.category,
		        d.id, d.name, d.category, d.description, d.url, d.postcode,
		        d.lat, d.lon, d.source
		 FROM events e JOIN destinations d ON d.id = e.destination_id
		 WHERE e.end_date >= ? AND e.start_date <= ?
		 ORDER BY e.start_date`, today, horizon)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []Event{}
	for rows.Next() {
		var e Event
		d := &e.Destination
		if err := rows.Scan(&e.ID, &e.Title, &e.Description, &e.URL,
			&e.StartDate, &e.EndDate, &e.Category,
			&d.ID, &d.Name, &d.Category, &d.Description, &d.URL,
			&d.Postcode, &d.Lat, &d.Lon, &d.Source); err != nil {
			return nil, err
		}
		if len(categories) > 0 && !slices.Contains(categories, d.Category) {
			continue
		}
		d.DistanceKm = HaversineKm(lat, lon, d.Lat, d.Lon)
		d.DriveMinutes = DriveMinutes(d.DistanceKm)
		e.Ongoing = isOngoing(e.StartDate, e.EndDate)
		if d.DriveMinutes <= maxMinutes {
			result = append(result, e)
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// Special events first, then standing programmes; nearest first within
	// each, as asked for.
	slices.SortFunc(result, func(a, b Event) int {
		if a.Ongoing != b.Ongoing {
			if a.Ongoing {
				return 1
			}
			return -1
		}
		switch {
		case a.Destination.DriveMinutes < b.Destination.DriveMinutes:
			return -1
		case a.Destination.DriveMinutes > b.Destination.DriveMinutes:
			return 1
		}
		return strings.Compare(a.StartDate, b.StartDate)
	})
	return result, nil
}

// Counts returns row counts for the status endpoint.
func (s *Store) Counts() (destinations, events, postcodes int, err error) {

	if err = s.DB.QueryRow(`SELECT COUNT(*) FROM destinations`).Scan(&destinations); err != nil {
		return
	}
	if err = s.DB.QueryRow(`SELECT COUNT(*) FROM events`).Scan(&events); err != nil {
		return
	}
	err = s.DB.QueryRow(`SELECT COUNT(*) FROM postcodes`).Scan(&postcodes)
	return
}

// LatestScrapeRuns returns the most recent recorded run for each source.
func (s *Store) LatestScrapeRuns() ([]SourceStatus, error) {

	rows, err := s.DB.Query(
		`SELECT source, started_at, COALESCE(finished_at, ''), COALESCE(ok, 0), message
		 FROM scrape_runs
		 WHERE id IN (SELECT MAX(id) FROM scrape_runs GROUP BY source)
		 ORDER BY source`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := []SourceStatus{}
	for rows.Next() {
		var r SourceStatus
		var ok int
		if err := rows.Scan(&r.Source, &r.StartedAt, &r.FinishedAt, &ok, &r.Message); err != nil {
			return nil, err
		}
		r.OK = ok != 0
		result = append(result, r)
	}
	return result, rows.Err()
}
