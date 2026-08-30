package main

import (
	"log/slog"
	"net/http"
	"os"
	"runtime"

	"github.com/andew42/daysout/servers"
	"github.com/andew42/daysout/store"
)

// Main
func main() {

	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, nil)))
	slog.Info("environment", "gover", runtime.Version(), "goos", runtime.GOOS, "goarch", runtime.GOARCH)

	// DAYSOUT is the install base path (unset in development, when the Vite
	// dev server serves the frontend and data lives beside the working dir).
	contentBasePath := os.Getenv("DAYSOUT")
	if contentBasePath == "" {
		slog.Warn("DAYSOUT environment variable not set — static content will not be served (use Vite dev server)")
	} else {
		slog.Info("content base path", "contentBasePath", contentBasePath)
	}

	// DAYSOUT_DATA overrides where the database, tile archive and basemap
	// assets live; defaults to <base>/data or ./data in development.
	dataDir := os.Getenv("DAYSOUT_DATA")
	if dataDir == "" {
		if contentBasePath != "" {
			dataDir = contentBasePath + "/data"
		} else {
			dataDir = "data"
		}
	}
	slog.Info("data directory", "dataDir", dataDir)

	s, err := store.Open(dataDir)
	if err != nil {
		slog.Error("open store", "err", err)
		os.Exit(1)
	}
	defer s.Close()

	if err := s.SeedIfEmpty(); err != nil {
		slog.Error("seed database", "err", err)
		os.Exit(1)
	}

	http.HandleFunc("/api/geocode", servers.GeocodeHandler(s))
	http.HandleFunc("/api/destinations", servers.DestinationsHandler(s))
	http.HandleFunc("/api/events", servers.EventsHandler(s))
	http.HandleFunc("/api/status", servers.StatusHandler(s))
	http.HandleFunc("/api/sources", servers.SourcesHandler(s))

	// Offline map: single-file tile archive plus the basemap's fonts/sprites,
	// all placed in the data directory by setup/get-tiles.sh.
	http.HandleFunc("/tiles/uk.pmtiles", servers.TilesHandler(dataDir))
	http.Handle("/basemap/", http.StripPrefix("/basemap/",
		http.FileServer(http.Dir(dataDir+"/basemap"))))

	if contentBasePath != "" {
		http.Handle("/", servers.SpaHandler(contentBasePath+"/frontend/build"))
	}

	port := os.Getenv("DAYSOUT_PORT")
	if port == "" {
		port = "8080"
	}
	slog.Info("serving", "port", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		slog.Error(err.Error())
	}
}
