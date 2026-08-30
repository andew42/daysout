package servers

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

// A deploy that lands but does not reach the browser looks exactly like a
// change that was never made, and cost a round of chasing the wrong bug.
func TestThePageIsRevalidatedButAssetsAreNot(t *testing.T) {

	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "index.html"),
		[]byte("<!doctype html>"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(dir, "assets"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "assets", "index-abc123.js"),
		[]byte("console.log(1)"), 0o644); err != nil {
		t.Fatal(err)
	}

	handler := SpaHandler(dir)
	for _, c := range []struct {
		path, want string
	}{
		{"/", "no-cache"},
		{"/events", "no-cache"}, // the SPA fallback serves index.html
		{"/assets/index-abc123.js", "public, max-age=31536000, immutable"},
	} {
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, c.path, nil))
		if got := recorder.Header().Get("Cache-Control"); got != c.want {
			t.Errorf("%s: Cache-Control = %q, want %q", c.path, got, c.want)
		}
	}
}
