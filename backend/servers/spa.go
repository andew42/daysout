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
