package servers

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// SpaHandler serves the frontend build, falling back to index.html for paths
// that aren't real files so client-side routes (/events, /settings) survive a
// hard refresh.
func SpaHandler(buildDir string) http.Handler {

	fileServer := http.FileServer(http.Dir(buildDir))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {

		setCaching(w, r.URL.Path)

		path := filepath.Join(buildDir, filepath.Clean(strings.TrimPrefix(r.URL.Path, "/")))
		if info, err := os.Stat(path); err != nil || info.IsDir() {
			if r.URL.Path != "/" {
				http.ServeFile(w, r, filepath.Join(buildDir, "index.html"))
				return
			}
		}
		fileServer.ServeHTTP(w, r)
	})
}

// setCaching tells the browser which of these files it may reuse blind.
//
// Nothing said anything before, so browsers applied their own heuristic to
// index.html and could go on serving a deployed-over copy — which points at
// the previous build's hashed bundle, so a deploy can land and the page not
// change. The build gives every asset a content hash in its name, so those
// are safe to keep forever, and index.html is the one file that must be
// re-checked.
func setCaching(w http.ResponseWriter, urlPath string) {
	if strings.HasPrefix(urlPath, "/assets/") {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
		return
	}
	// no-cache means "revalidate", not "don't store": a 304 keeps it cheap.
	w.Header().Set("Cache-Control", "no-cache")
}
