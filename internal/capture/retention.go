package capture

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"
)

// PruneResult describes one traffic prune.
type PruneResult struct {
	At          time.Time
	RowsDeleted int64
	Err         string
}

// pruneCutoff formats the RFC3339 cutoff for traffic.ts comparison.
//
// traffic.ts holds UTC RFC3339Nano text with trailing zeros trimmed, e.g.
// "2026-08-07T08:23:21.238669Z" or "2026-08-07T08:23:21Z". The cutoff is
// formatted to the second and WITHOUT the "Z", so a plain string `ts < cutoff`
// is exact at second granularity for every fractional-second spelling: any row
// in the cutoff second is longer than (hence greater than) the cutoff prefix
// and is kept. The idx_traffic_ts index is used.
func pruneCutoff(now time.Time, retentionDays int) string {
	return now.UTC().Add(-time.Duration(retentionDays) * 24 * time.Hour).Format("2006-01-02T15:04:05")
}

// deleteExpiredTraffic deletes rows older than the cutoff in bounded batches,
// never touching session-linked rows. Returns total rows deleted.
func deleteExpiredTraffic(ctx context.Context, db *sql.DB, cutoff string) (int64, error) {
	var total int64
	for {
		if err := ctx.Err(); err != nil {
			return total, err
		}
		res, err := db.ExecContext(ctx,
			`DELETE FROM traffic WHERE id IN (
				SELECT id FROM traffic WHERE session_id IS NULL AND ts < ? LIMIT ?)`,
			cutoff, pruneBatchSize)
		if err != nil {
			return total, fmt.Errorf("prune traffic batch: %w", err)
		}
		n, _ := res.RowsAffected()
		total += n
		if n < pruneBatchSize {
			return total, nil
		}
	}
}

// reclaimSpace releases freelist pages to the OS: bounded incremental_vacuum
// chunks, then (when rows were deleted) a TRUNCATE checkpoint so the WAL and
// main file actually shrink.
func reclaimSpace(ctx context.Context, db *sql.DB, deleted int64) error {
	prev := int64(-1)
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		var free int64
		if err := db.QueryRowContext(ctx, "PRAGMA freelist_count").Scan(&free); err != nil {
			return fmt.Errorf("freelist_count: %w", err)
		}
		// Stop when nothing is left, or when a vacuum call made no progress
		// (a database that is not auto_vacuum=INCREMENTAL ignores the pragma).
		if free == 0 || (prev >= 0 && free >= prev) {
			break
		}
		prev = free
		if _, err := db.ExecContext(ctx, fmt.Sprintf("PRAGMA incremental_vacuum(%d)", vacuumChunkPages)); err != nil {
			return fmt.Errorf("incremental_vacuum: %w", err)
		}
	}
	if deleted > 0 {
		var busy, logPages, ckpt int64
		if err := db.QueryRowContext(ctx, "PRAGMA wal_checkpoint(TRUNCATE)").Scan(&busy, &logPages, &ckpt); err != nil {
			return fmt.Errorf("wal_checkpoint: %w", err)
		}
	}
	return nil
}

// Prune deletes expired, non-session traffic rows and reclaims space. It is a
// no-op when retention is disabled. Safe to call concurrently with Insert.
func (s *Store) Prune(ctx context.Context) (PruneResult, error) {
	s.pruneMu.Lock()
	defer s.pruneMu.Unlock()

	res := PruneResult{At: s.now().UTC()}
	if s.cfg.RetentionDays <= 0 {
		return res, nil
	}
	start := time.Now()
	deleted, err := deleteExpiredTraffic(ctx, s.db, pruneCutoff(s.now(), s.cfg.RetentionDays))
	res.RowsDeleted = deleted
	if err == nil {
		err = reclaimSpace(ctx, s.db, deleted)
	}
	if err != nil {
		res.Err = err.Error()
	}
	s.lastPruneMu.Lock()
	s.lastPrune = res
	s.lastPruneMu.Unlock()
	if err != nil && ctx.Err() != nil {
		slog.Info("traffic prune interrupted by shutdown", "rows_deleted", deleted)
		return res, err
	}
	if err != nil {
		slog.Error("traffic prune failed", "rows_deleted", deleted, "error", err)
		return res, err
	}
	slog.Info("traffic prune complete", "rows_deleted", deleted, "retention_days", s.cfg.RetentionDays, "duration", time.Since(start).Round(time.Millisecond))
	return res, nil
}

// startPruneLoop runs a prune at startup and then every PruneInterval until
// Close.
func (s *Store) startPruneLoop() {
	if s.cfg.NoBackgroundPrune || s.cfg.RetentionDays <= 0 {
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	s.pruneCancel = cancel
	s.pruneWG.Add(1)
	go func() {
		defer s.pruneWG.Done()
		_, _ = s.Prune(ctx)
		if s.cfg.PruneInterval <= 0 {
			return
		}
		t := time.NewTicker(s.cfg.PruneInterval)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				_, _ = s.Prune(ctx)
			}
		}
	}()
}

func (s *Store) stopPruneLoop() {
	if s.pruneCancel != nil {
		s.pruneCancel()
	}
	s.pruneWG.Wait()
}

// ensureIncrementalVacuum makes the database auto_vacuum=INCREMENTAL.
//
// Fresh (empty) database: just set the pragma before any table exists.
// Existing database: a one-time VACUUM is required. It first prunes expired
// rows (so the rewrite is smaller), checks free disk space, logs start/end/
// duration, and on any problem logs a warning and skips (retried on the next
// start). It never returns an error that should fail startup.
func ensureIncrementalVacuum(db *sql.DB, dbPath string, cfg Config, now func() time.Time) {
	var mode int
	if err := db.QueryRow("PRAGMA auto_vacuum").Scan(&mode); err != nil {
		slog.Warn("auto_vacuum: read mode failed; skipping", "error", err)
		return
	}
	if mode == 2 {
		return
	}
	var tables int
	if err := db.QueryRow("SELECT COUNT(*) FROM sqlite_master").Scan(&tables); err != nil {
		slog.Warn("auto_vacuum: inspect schema failed; skipping", "error", err)
		return
	}
	if tables == 0 {
		if _, err := db.Exec("PRAGMA auto_vacuum = INCREMENTAL"); err != nil {
			slog.Warn("auto_vacuum: set on fresh database failed", "error", err)
		}
		return
	}

	ctx := context.Background()
	if cfg.RetentionDays > 0 {
		if exists, _ := tableExistsDB(db, "traffic"); exists {
			if n, err := deleteExpiredTraffic(ctx, db, pruneCutoff(now(), cfg.RetentionDays)); err != nil {
				slog.Warn("auto_vacuum: pre-migration prune failed", "error", err)
			} else if n > 0 {
				slog.Info("auto_vacuum: pre-migration prune", "rows_deleted", n)
			}
		}
	}

	var pageCount, freePages, pageSize int64
	_ = db.QueryRow("PRAGMA page_count").Scan(&pageCount)
	_ = db.QueryRow("PRAGMA freelist_count").Scan(&freePages)
	_ = db.QueryRow("PRAGMA page_size").Scan(&pageSize)
	live := liveDBBytes(pageCount, freePages, pageSize)
	// VACUUM rebuilds into a temp file and then through the WAL: budget the
	// live size plus headroom on the DB volume and the temp volume.
	need := live + live/4 + 64<<20
	for _, dir := range uniqueDirs(filepath.Dir(dbPath), os.TempDir()) {
		if free, ok := freeDiskBytes(dir); ok && free < need {
			slog.Warn("auto_vacuum: not enough free disk space for one-time VACUUM; skipping migration (will retry next start)",
				"dir", dir, "free_bytes", free, "need_bytes", need)
			return
		}
	}

	slog.Info("auto_vacuum: converting database to INCREMENTAL (one-time VACUUM)", "live_bytes", live, "db", dbPath)
	t0 := time.Now()
	if _, err := db.Exec("PRAGMA auto_vacuum = INCREMENTAL"); err != nil {
		slog.Warn("auto_vacuum: set pragma failed; skipping", "error", err)
		return
	}
	if _, err := db.Exec("VACUUM"); err != nil {
		slog.Warn("auto_vacuum: VACUUM failed; continuing without conversion", "error", err, "duration", time.Since(t0).Round(time.Millisecond))
		return
	}
	var busy, logPages, ckpt int64
	_ = db.QueryRow("PRAGMA wal_checkpoint(TRUNCATE)").Scan(&busy, &logPages, &ckpt)
	slog.Info("auto_vacuum: one-time VACUUM finished", "duration", time.Since(t0).Round(time.Millisecond))
}

func uniqueDirs(dirs ...string) []string {
	seen := map[string]bool{}
	var out []string
	for _, d := range dirs {
		if d == "" || seen[d] {
			continue
		}
		seen[d] = true
		out = append(out, d)
	}
	return out
}

func tableExistsDB(db *sql.DB, table string) (bool, error) {
	var n int
	err := db.QueryRow("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", table).Scan(&n)
	return n > 0, err
}
