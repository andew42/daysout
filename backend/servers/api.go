package servers

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/andew42/daysout/store"
)

func writeJSON(w http.ResponseWriter, status int, v any) {

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		slog.Error("encode response", "err", err)
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// home resolves the postcode query parameter to coordinates, writing the
// error response itself when it can't.
func home(s *store.Store, w http.ResponseWriter, r *http.Request) (lat, lon float64, ok bool) {

	pc := r.URL.Query().Get("postcode")
	if pc == "" {
		writeError(w, http.StatusBadRequest, "postcode query parameter is required")
		return 0, 0, false
	}
	lat, lon, err := s.Geocode(pc)
	if err != nil {
		writeError(w, http.StatusNotFound, err.Error())
		return 0, 0, false
	}
	return lat, lon, true
}

func queryFloat(r *http.Request, name string, def float64) float64 {

	if v := r.URL.Query().Get(name); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil && f > 0 {
			return f
		}
	}
	return def
}

func queryInt(r *http.Request, name string, def int) int {

	if v := r.URL.Query().Get(name); v != "" {
		if i, err := strconv.Atoi(v); err == nil && i > 0 {
			return i
		}
	}
	return def
}

func queryCategories(r *http.Request) []string {

	v := r.URL.Query().Get("categories")
	if v == "" {
		return nil
	}
	return strings.Split(v, ",")
}

// GeocodeHandler GET /api/geocode?postcode=SN13+8AA
func GeocodeHandler(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		pc := r.URL.Query().Get("postcode")
		lat, lon, err := s.Geocode(pc)
		if err != nil {
			writeError(w, http.StatusNotFound, err.Error())
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"postcode": store.NormalisePostcode(pc), "lat": lat, "lon": lon})
	}
}

// DestinationsHandler GET /api/destinations?postcode=…&minutes=60&categories=a,b
func DestinationsHandler(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		lat, lon, ok := home(s, w, r)
		if !ok {
			return
		}
		minutes := queryFloat(r, "minutes", 60)
		dests, err := s.Destinations(lat, lon, minutes, queryCategories(r))
		if err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"home":         map[string]float64{"lat": lat, "lon": lon},
			"minutes":      minutes,
			"destinations": dests,
		})
	}
}

// EventsHandler GET /api/events?postcode=…&days=7&minutes=60&categories=a,b
func EventsHandler(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		lat, lon, ok := home(s, w, r)
		if !ok {
			return
		}
		minutes := queryFloat(r, "minutes", 60)
		days := queryInt(r, "days", 7)
		events, err := s.Events(lat, lon, minutes, days, queryCategories(r))
		if err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"home":    map[string]float64{"lat": lat, "lon": lon},
			"minutes": minutes,
			"days":    days,
			"events":  events,
		})
	}
}

// StatusHandler GET /api/status — row counts, tile availability and scrape
// freshness for the UI footer.
func StatusHandler(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		destinations, events, postcodes, err := s.Counts()
		if err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
		runs, err := s.LatestScrapeRuns()
		if err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
		_, tilesErr := os.Stat(filepath.Join(s.DataDir, "uk.pmtiles"))
		writeJSON(w, http.StatusOK, map[string]any{
			"destinations":   destinations,
			"events":         events,
			"postcodes":      postcodes,
			"tilesAvailable": tilesErr == nil,
			"scrapes":        runs,
		})
	}
}

// TilesHandler GET /tiles/uk.pmtiles — http.ServeFile provides the HTTP
// range-request support the pmtiles client library needs.
func TilesHandler(dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, filepath.Join(dataDir, "uk.pmtiles"))
	}
}

// SourcesHandler /api/sources — the sites the scraper visits.
//
//	GET    lists them, with what each is contributing
//	POST   {"url":…, "category":…, "kind":…, "venuePostcode":…} adds one
//	DELETE ?name=… removes one, and remembers that it was removed
//
// Adding a source only writes a row: the server itself never fetches
// anything, so the site is visited by the scraper on its next run.
func SourcesHandler(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		switch r.Method {
		case http.MethodGet:
			sources, err := s.Sources()
			if err != nil {
				writeError(w, http.StatusInternalServerError, err.Error())
				return
			}
			writeJSON(w, http.StatusOK, map[string]any{
				"sources": sources,
				"kinds":   store.SourceKinds,
			})

		case http.MethodPost:
			var body struct {
				URL           string `json:"url"`
				Category      string `json:"category"`
				Kind          string `json:"kind"`
				VenueName     string `json:"venueName"`
				VenuePostcode string `json:"venuePostcode"`
			}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				writeError(w, http.StatusBadRequest, "expected a JSON body")
				return
			}
			source, err := s.AddSource(body.URL, body.Category, body.Kind,
				body.VenueName, body.VenuePostcode)
			if err != nil {
				// Everything AddSource rejects is something the person
				// typed, so it is a 400 with the reason they need to read.
				writeError(w, http.StatusBadRequest, err.Error())
				return
			}
			slog.Info("source added", "name", source.Name, "url", source.URL)
			writeJSON(w, http.StatusCreated, source)

		case http.MethodDelete:
			name := r.URL.Query().Get("name")
			if err := s.DeleteSource(name); err != nil {
				writeError(w, http.StatusBadRequest, err.Error())
				return
			}
			writeJSON(w, http.StatusOK, map[string]any{"deleted": name})

		default:
			w.Header().Set("Allow", "GET, POST, DELETE")
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
	}
}

// SourceContributionHandler GET /api/sources/contribution?name=…
//
// What one source has actually put in the database — the list behind the
// events/places pill on the Sources page. A count tells you a source is
// working; only the rows tell you whether what it produced is any good.
func SourceContributionHandler(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		if r.Method != http.MethodGet {
			w.Header().Set("Allow", "GET")
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		name := r.URL.Query().Get("name")
		if name == "" {
			writeError(w, http.StatusBadRequest, "name is required")
			return
		}
		contribution, err := s.Contribution(name)
		if err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
		writeJSON(w, http.StatusOK, contribution)
	}
}
