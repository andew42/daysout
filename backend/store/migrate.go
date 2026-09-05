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
}

// Tables that used to hold sources as rows. Dropped rather than left
// orphaned: a schema that still describes a feature is a schema somebody
// will believe. Any rows a person added through the old UI go with them,
// which costs nothing they can still use — the engine that ran those rows
// is gone too, so they had stopped being sources before this ran.
var droppedTables = []string{"sources", "removed_sources"}

func migrate(db *sql.DB) error {

	for _, table := range droppedTables {
		var name string
		err := db.QueryRow(
			`SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?`,
			table).Scan(&name)
		if err == sql.ErrNoRows {
			continue
		}
		if err != nil {
			return fmt.Errorf("look for %s: %w", table, err)
		}
		if _, err := db.Exec("DROP TABLE " + table); err != nil {
			return fmt.Errorf("drop %s: %w", table, err)
		}
		slog.Info("migrated database", "droppedTable", table)
	}

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
