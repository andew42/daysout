package store

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	_ "modernc.org/sqlite"
)

// Store wraps the SQLite database shared with the scraper process.
type Store struct {
	DB      *sql.DB
	DataDir string
}

// Open opens (creating if necessary) the database in dataDir and applies the
// schema. WAL mode lets the scraper write while the server reads.
func Open(dataDir string) (*Store, error) {

	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		return nil, fmt.Errorf("create data dir: %w", err)
	}

	dsn := "file:" + filepath.Join(dataDir, "daysout.db") +
		"?_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)&_pragma=foreign_keys(1)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open database: %w", err)
	}

	if _, err := db.Exec(schema); err != nil {
		db.Close()
		return nil, fmt.Errorf("apply schema: %w", err)
	}
	if err := migrate(db); err != nil {
		db.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}

	return &Store{DB: db, DataDir: dataDir}, nil
}

// Close closes the underlying database.
func (s *Store) Close() error {
	return s.DB.Close()
}
