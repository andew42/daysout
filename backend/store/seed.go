package store

import (
	"log/slog"
	"time"
)

// A handful of well-known destinations so a fresh install shows something
// before the scraper has run. Coordinates are approximate (property centre).
// Rows carry source='seed'; the scraper deletes them once real data exists.
var seedDestinations = []struct {
	name, category, description, url, postcode string
	lat, lon                                   float64
}{
	{"Stourhead", "garden", "National Trust landscape garden and Palladian house", "https://www.nationaltrust.org.uk/visit/wiltshire/stourhead", "BA12 6QF", 51.1054, -2.3187},
	{"Lacock Abbey", "historic-house", "National Trust abbey, village and Fox Talbot museum", "https://www.nationaltrust.org.uk/visit/wiltshire/lacock", "SN15 2LG", 51.4147, -2.1180},
	{"Avebury", "historic-house", "National Trust stone circle and manor", "https://www.nationaltrust.org.uk/visit/wiltshire/avebury", "SN8 1RD", 51.4287, -1.8548},
	{"Dyrham Park", "historic-house", "National Trust baroque house and deer park", "https://www.nationaltrust.org.uk/visit/bath-bristol/dyrham-park", "SN14 8HY", 51.4820, -2.3743},
	{"Hidcote", "garden", "National Trust Arts and Crafts garden", "https://www.nationaltrust.org.uk/visit/gloucestershire-cotswolds/hidcote", "GL55 6LR", 52.0801, -1.7405},
	{"Stonehenge", "historic-house", "English Heritage prehistoric stone circle", "https://www.english-heritage.org.uk/visit/places/stonehenge/", "SP4 7DE", 51.1789, -1.8262},
	{"Old Sarum", "historic-house", "English Heritage Iron Age hillfort and ruined castle", "https://www.english-heritage.org.uk/visit/places/old-sarum/", "SP1 3SD", 51.0930, -1.8049},
	{"Blenheim Palace", "historic-house", "Baroque palace, park and formal gardens", "https://www.blenheimpalace.com/", "OX20 1UL", 51.8414, -1.3612},
	{"RHS Garden Wisley", "garden", "Royal Horticultural Society flagship garden", "https://www.rhs.org.uk/gardens/wisley", "GU23 6QB", 51.3120, -0.4740},
	{"Kew Gardens", "garden", "Royal Botanic Gardens, Kew", "https://www.kew.org/", "TW9 3AE", 51.4787, -0.2956},
	{"IWM Duxford", "airfield", "Imperial War Museum airfield and aviation museum", "https://www.iwm.org.uk/visits/iwm-duxford", "CB22 4QR", 52.0943, 0.1312},
	{"Shuttleworth", "airfield", "Historic aircraft collection and flying displays at Old Warden", "https://www.shuttleworth.org/", "SG18 9EP", 52.0855, -0.3251},
	{"Fleet Air Arm Museum", "airfield", "Naval aviation museum at RNAS Yeovilton", "https://www.nmrn.org.uk/visit-us/fleet-air-arm-museum", "BA22 8HT", 51.0089, -2.6386},
}

// SeedIfEmpty populates demo destinations (plus a couple of events next
// weekend) when the destinations table has no rows at all.
func (s *Store) SeedIfEmpty() error {

	var n int
	if err := s.DB.QueryRow(`SELECT COUNT(*) FROM destinations`).Scan(&n); err != nil {
		return err
	}
	if n > 0 {
		return nil
	}

	now := time.Now().Format(time.RFC3339)
	for _, d := range seedDestinations {
		_, err := s.DB.Exec(
			`INSERT INTO destinations
			   (name, category, description, url, postcode, lat, lon,
			    source, source_id, first_seen, last_seen)
			 VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', ?, ?, ?)`,
			d.name, d.category, d.description, d.url, d.postcode, d.lat, d.lon,
			d.name, now, now)
		if err != nil {
			return err
		}
	}

	// Demo events on the coming weekend so the events view isn't empty.
	saturday := time.Now()
	for saturday.Weekday() != time.Saturday {
		saturday = saturday.AddDate(0, 0, 1)
	}
	sat := saturday.Format("2006-01-02")
	sun := saturday.AddDate(0, 0, 1).Format("2006-01-02")
	demoEvents := []struct{ dest, title, start, end string }{
		{"Stourhead", "Guided garden walk (demo seed data)", sat, sat},
		{"Shuttleworth", "Flying day (demo seed data)", sun, sun},
		{"Lacock Abbey", "Village history weekend (demo seed data)", sat, sun},
	}
	for _, e := range demoEvents {
		_, err := s.DB.Exec(
			`INSERT INTO events
			   (destination_id, title, description, url, start_date, end_date,
			    source, source_id, last_seen)
			 SELECT id, ?, 'Placeholder event created by seed data; replaced by the scraper.',
			        url, ?, ?, 'seed', ?, ?
			 FROM destinations WHERE name = ? AND source = 'seed'`,
			e.title, e.start, e.end, e.dest+"/"+e.title, now, e.dest)
		if err != nil {
			return err
		}
	}

	slog.Info("seeded demo destinations", "count", len(seedDestinations))
	return nil
}
