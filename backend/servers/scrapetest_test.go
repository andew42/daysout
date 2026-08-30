package servers

import (
	"strings"
	"testing"
)

func TestSourceNamesThatMayReachACommandLine(t *testing.T) {

	// argv is not a shell, so quoting is not the worry — a name that looks
	// like a flag is. "--max-pages" as a source name would be read by the
	// scraper as an option rather than a value.
	valid := []string{"ngs-find-a-garden", "english_heritage", "example.org", "a1"}
	for _, name := range valid {
		if !safeSourceName.MatchString(name) {
			t.Errorf("%q should be an acceptable source name", name)
		}
	}

	invalid := []string{"", "--max-pages", "-x", "a b", "a;b", "a$(b)", "a/b", "a\nb"}
	for _, name := range invalid {
		if safeSourceName.MatchString(name) {
			t.Errorf("%q should be refused as a source name", name)
		}
	}
}

func TestTailKeepsTheEndAndWholeLines(t *testing.T) {

	// The end of the log is where the summary and the unplaced-event lines
	// are, so a truncated log must keep the tail, not the head.
	log := "first line\nsecond line\nthird line\nlast line"
	if got := tail(log, 1000); got != log {
		t.Errorf("a short log should come back whole, got %q", got)
	}

	cut := tail(log, 20)
	if !strings.HasSuffix(cut, "last line") {
		t.Errorf("tail should end with the last line, got %q", cut)
	}
	if !strings.HasPrefix(cut, "…\n") {
		t.Errorf("a truncated log should say so, got %q", cut)
	}
	// Never start mid-line: a half-sentence reads as corruption.
	for _, line := range strings.Split(strings.TrimPrefix(cut, "…\n"), "\n") {
		if line != "" && !strings.Contains(log, line) {
			t.Errorf("line %q is not a whole line of the log", line)
		}
	}
}

func TestOnlyTheScrapersOwnLogIsShown(t *testing.T) {

	// A failed fetch buries the one useful line under a Python traceback.
	output := `INFO daysout_scraper.pipeline: example: scanning 3 pages
Traceback (most recent call last):
  File "/opt/daysout/scraper/daysout_scraper/fetch.py", line 103, in get
    response = self.session.get(url, timeout=TIMEOUT_SECONDS)
requests.exceptions.ConnectionError: Max retries exceeded
ERROR daysout_scraper.pipeline: example failed`

	got := scraperLogLines(output)
	if strings.Contains(got, "Traceback") || strings.Contains(got, "File \"") {
		t.Errorf("traceback frames should be dropped, got:\n%s", got)
	}
	for _, want := range []string{"scanning 3 pages", "example failed"} {
		if !strings.Contains(got, want) {
			t.Errorf("the scraper's own log line %q should survive, got:\n%s", want, got)
		}
	}
}

func TestOutputWithNoRecognisableLogIsKept(t *testing.T) {

	// Better to show something unexpected than an empty panel.
	output := "python3: No module named daysout_scraper"
	if got := scraperLogLines(output); got != output {
		t.Errorf("unrecognised output should pass through, got %q", got)
	}
}
