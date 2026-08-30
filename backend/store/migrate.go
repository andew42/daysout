package store

import (
	"database/sql"
	"fmt"
	"log/slog"
)

// Columns added after the first release. A fresh database gets them from
// schema.go; this brings an existing one up to the same shape, since SQLite
// has no "ADD COLUMN IF NOT EXISTS" and the container's data must survive.
// Keep both in step: schema.go describes the current shape, this upgrades
// databases created before it.
var addedColumns = []struct{ table, column, definition string }{
	{"events", "category", "TEXT NOT NULL DEFAULT ''"},
	{"sources", "venue_name", "TEXT NOT NULL DEFAULT ''"},
	{"sources", "venue_postcode", "TEXT NOT NULL DEFAULT ''"},
}

func migrate(db *sql.DB) error {

	for _, c := range addedColumns {
		has, err := hasColumn(db, c.table, c.column)
		if err != nil {
			return err
		}
		if has {
			continue
		}
		statement := fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", c.table, c.column, c.definition)
		if _, err := db.Exec(statement); err != nil {
			return fmt.Errorf("add %s.%s: %w", c.table, c.column, err)
		}
		slog.Info("migrated database", "table", c.table, "addedColumn", c.column)
	}
	return nil
}

func hasColumn(db *sql.DB, table, column string) (bool, error) {

	rows, err := db.Query(fmt.Sprintf("PRAGMA table_info(%s)", table))
	if err != nil {
		return false, err
	}
	defer rows.Close()

	for rows.Next() {
		var (
			cid, notNull, primaryKey int
			name, columnType         string
			defaultValue             sql.NullString
		)
		if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			return false, err
		}
		if name == column {
			return true, nil
		}
	}
	return false, rows.Err()
}
