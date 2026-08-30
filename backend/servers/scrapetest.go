package servers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/andew42/daysout/store"
)

// Testing a source is the one thing the server does that reaches the
// internet, and it does so the only way anything here ever does: by
// running the scraper. Adding a site and then waiting until 05:30 to find
// out whether it publishes anything usable made the Sources tab a
// suggestion box, so this runs that one source now and reports back.
//
// The run is deliberately bounded (--max-pages), which the pipeline treats
// as a partial run: it looks at a sample of the site and is never allowed
// to purge rows it did not check. A test can therefore add data but never
// remove any.
const (
	testPageLimit  = "10"
	testTimeout    = 3 * time.Minute
	testOutputTail = 8000 // bytes of scraper log returned to the browser
)

// Source names are ours (derived from the URL) but the table can also be
// edited by hand, so check before putting one on a command line — a name
// starting with "-" would be read as a flag.
var safeSourceName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]*$`)

// One test at a time. Without this, an impatient double-click would send
// two crawls at the same site at once, which is exactly the rudeness the
// rate limiter exists to prevent.
var testRunning sync.Mutex

// scraperDir is where `python3 -m daysout_scraper` can be run.
func scraperDir() string {
	if base := os.Getenv("DAYSOUT"); base != "" {
		return filepath.Join(base, "scraper")
	}
	// Development: the server runs from backend/, the scraper is its sibling.
	if info, err := os.Stat(filepath.Join("..", "scraper", "daysout_scraper")); err == nil && info.IsDir() {
		return filepath.Join("..", "scraper")
	}
	return "scraper"
}

// TestSourceHandler POST /api/sources/test {"name": …}
//
// Runs the scraper for one source and returns what it did, including the
// scraper's own log — which says far more than a row count: which pages it
// looked at, how many events it read, and the venue of any event it could
// not place.
func TestSourceHandler(s *store.Store, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {

		if r.Method != http.MethodPost {
			w.Header().Set("Allow", "POST")
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}

		var body struct {
			Name string `json:"name"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeError(w, http.StatusBadRequest, "expected a JSON body")
			return
		}
		if !safeSourceName.MatchString(body.Name) {
			writeError(w, http.StatusBadRequest, "not a valid source name")
			return
		}

		// The source must exist: this is what stops an arbitrary string
		// reaching the scraper's --sources argument.
		sources, err := s.Sources()
		if err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
		found := false
		for _, source := range sources {
			if source.Name == body.Name {
				found = true
				break
			}
		}
		if !found {
			writeError(w, http.StatusBadRequest,
				fmt.Sprintf("no source named %q", body.Name))
			return
		}

		if !testRunning.TryLock() {
			writeError(w, http.StatusConflict,
				"another source is being tested — try again in a moment")
			return
		}
		defer testRunning.Unlock()

		started := time.Now()
		output, runErr := runScraper(r.Context(), body.Name, dataDir)
		elapsed := time.Since(started)

		// The scrape_runs row is the scraper's own verdict, and it is
		// written whether the run succeeded or not.
		ok, message := s.LatestRun(body.Name)
		if message == "" && runErr != nil {
			message = runErr.Error()
		}
		slog.Info("source tested", "name", body.Name, "ok", ok,
			"seconds", elapsed.Seconds(), "message", message)

		writeJSON(w, http.StatusOK, map[string]any{
			"name":     body.Name,
			"ok":       ok,
			"message":  message,
			"output":   tail(scraperLogLines(output), testOutputTail),
			"seconds":  int(elapsed.Seconds() + 0.5),
			"exitedOK": runErr == nil,
		})
	}
}

// runScraper runs one source and returns the scraper's combined output.
// A non-zero exit is not an error worth failing the request over: the
// scraper exits 1 when a source yields nothing, and its log and the
// scrape_runs row explain why far better than a status code.
func runScraper(parent context.Context, name, dataDir string) (string, error) {

	ctx, cancel := context.WithTimeout(parent, testTimeout)
	defer cancel()

	command := exec.CommandContext(ctx, "python3", "-m", "daysout_scraper",
		"--sources", name, "--max-pages", testPageLimit, "--keep-seed")
	command.Dir = scraperDir()
	command.Env = append(os.Environ(), "DAYSOUT_DATA="+dataDir)

	output, err := command.CombinedOutput()
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return string(output), fmt.Errorf(
			"gave up after %s — the site is slow, or the crawl is large",
			testTimeout)
	}
	return string(output), err
}

// scraperLogLines keeps the scraper's own log and drops everything else.
//
// A failing fetch produces a forty-line Python traceback, which tells the
// person who pressed the button nothing they can act on and buries the one
// line that does — the summary the pipeline logs. Log lines are
// "LEVEL logger: message"; traceback frames are not. The full output still
// goes to the server's journal.
func scraperLogLines(output string) string {

	var kept []string
	for _, line := range strings.Split(output, "\n") {
		if logLine.MatchString(line) {
			kept = append(kept, line)
		}
	}
	if len(kept) == 0 {
		return output // nothing recognisable: better the raw text than nothing
	}
	return strings.Join(kept, "\n")
}

var logLine = regexp.MustCompile(`^(DEBUG|INFO|WARNING|ERROR|CRITICAL) `)

// tail keeps the end of the log, which is where a source's own summary and
// its unplaced-event lines are.
func tail(text string, limit int) string {
	text = strings.TrimRight(text, "\n")
	if len(text) <= limit {
		return text
	}
	cut := text[len(text)-limit:]
	if i := strings.IndexByte(cut, '\n'); i >= 0 {
		cut = cut[i+1:]
	}
	return "…\n" + cut
}
