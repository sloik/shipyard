package capture

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

func newRetentionStore(t *testing.T, cfg Config) (*Store, string, string) {
	t.Helper()
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "r.db")
	jsonlPath := filepath.Join(dir, "r.jsonl")
	cfg.NoBackgroundPrune = true
	s, err := NewStoreWithConfig(dbPath, jsonlPath, cfg)
	if err != nil {
		t.Fatalf("NewStoreWithConfig: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s, dbPath, jsonlPath
}

func seedTraffic(t *testing.T, s *Store, ts time.Time, sessionID any, tag string) {
	t.Helper()
	if _, err := s.db.Exec(
		`INSERT INTO traffic (ts, direction, server_name, method, payload, status, session_id) VALUES (?,?,?,?,?,?,?)`,
		ts.UTC().Format(time.RFC3339Nano), DirectionClientToServer, "srv", tag, `{}`, "ok", sessionID); err != nil {
		t.Fatalf("seed: %v", err)
	}
}

func count(t *testing.T, s *Store, q string, args ...any) int {
	t.Helper()
	var n int
	if err := s.db.QueryRow(q, args...).Scan(&n); err != nil {
		t.Fatalf("%s: %v", q, err)
	}
	return n
}

// seedAgeMatrix seeds rows at 10/59/61/90 days, each with and without a session.
func seedAgeMatrix(t *testing.T, s *Store) {
	t.Helper()
	if _, err := s.db.Exec(`INSERT INTO sessions (name, server, status, started_at) VALUES ('s','srv','stopped','2026-01-01T00:00:00Z')`); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`INSERT INTO schema_snapshots (server_name, snapshot, captured_at) VALUES ('srv','{}','2026-01-01T00:00:00Z')`); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`INSERT INTO schema_changes (server_name, detected_at) VALUES ('srv','2026-01-01T00:00:00Z')`); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	for _, days := range []int{10, 59, 61, 90} {
		ts := now.Add(-time.Duration(days)*24*time.Hour - time.Minute)
		seedTraffic(t, s, ts, nil, fmt.Sprintf("plain-%d", days))
		seedTraffic(t, s, ts, 1, fmt.Sprintf("sess-%d", days))
	}
}

func TestPrune_KeepsRecentAndSessionRows(t *testing.T) {
	s, _, _ := newRetentionStore(t, DefaultConfig())
	seedAgeMatrix(t, s)

	res, err := s.Prune(context.Background())
	if err != nil {
		t.Fatalf("Prune: %v", err)
	}
	if res.RowsDeleted != 2 {
		t.Fatalf("deleted %d rows, want 2 (plain-61, plain-90)", res.RowsDeleted)
	}
	rows, err := s.db.Query(`SELECT method FROM traffic`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	got := map[string]bool{}
	for rows.Next() {
		var m string
		rows.Scan(&m)
		got[m] = true
	}
	want := []string{"plain-10", "plain-59", "sess-10", "sess-59", "sess-61", "sess-90"}
	if len(got) != len(want) {
		t.Fatalf("kept %v, want %v", got, want)
	}
	for _, w := range want {
		if !got[w] {
			t.Fatalf("missing %s in %v", w, got)
		}
	}
	for table, n := range map[string]int{"sessions": 1, "schema_snapshots": 1, "schema_changes": 1} {
		if c := count(t, s, "SELECT COUNT(*) FROM "+table); c != n {
			t.Fatalf("%s count = %d, want %d", table, c, n)
		}
	}
}

func TestPrune_NonVacuity_LongRetentionKeepsEverything(t *testing.T) {
	cfg := DefaultConfig()
	cfg.RetentionDays = 100
	s, _, _ := newRetentionStore(t, cfg)
	seedAgeMatrix(t, s)
	res, err := s.Prune(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if res.RowsDeleted != 0 || count(t, s, "SELECT COUNT(*) FROM traffic") != 8 {
		t.Fatalf("retention=100d must keep all 8 rows, deleted=%d", res.RowsDeleted)
	}
}

func TestPrune_DisabledRetentionKeepsEverything(t *testing.T) {
	for _, days := range []int{0, -5} {
		cfg := DefaultConfig()
		cfg.RetentionDays = days
		s, _, _ := newRetentionStore(t, cfg)
		seedAgeMatrix(t, s)
		if res, err := s.Prune(context.Background()); err != nil || res.RowsDeleted != 0 {
			t.Fatalf("days=%d: res=%+v err=%v", days, res, err)
		}
		if n := count(t, s, "SELECT COUNT(*) FROM traffic"); n != 8 {
			t.Fatalf("days=%d: %d rows, want 8", days, n)
		}
	}
}

func TestPrune_CutoffHandlesFractionalSecondSpellings(t *testing.T) {
	s, _, _ := newRetentionStore(t, DefaultConfig())
	fixed := time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)
	s.now = func() time.Time { return fixed }
	cut := fixed.Add(-60 * 24 * time.Hour) // 2026-09-14T12:00:00Z
	ins := func(ts, tag string) {
		if _, err := s.db.Exec(`INSERT INTO traffic (ts,direction,server_name,method,payload) VALUES (?,?,?,?,?)`, ts, "c2s", "srv", tag, "{}"); err != nil {
			t.Fatal(err)
		}
	}
	ins("2026-09-14T11:59:59.999999Z", "old-frac")
	ins("2026-09-14T11:59:59Z", "old-whole")
	ins("2026-09-14T12:00:00Z", "edge-whole")
	ins("2026-09-14T12:00:00.5Z", "edge-frac")
	ins("2026-09-14T12:00:01Z", "new")
	_ = cut
	if _, err := s.Prune(context.Background()); err != nil {
		t.Fatal(err)
	}
	if n := count(t, s, `SELECT COUNT(*) FROM traffic WHERE method LIKE 'old-%'`); n != 0 {
		t.Fatalf("old rows survived: %d", n)
	}
	if n := count(t, s, `SELECT COUNT(*) FROM traffic WHERE method IN ('edge-whole','edge-frac','new')`); n != 3 {
		t.Fatalf("boundary/new rows wrongly pruned, kept %d of 3", n)
	}
}

func TestPrune_ReclaimsFileSpace_AndAutoVacuumIncremental(t *testing.T) {
	s, dbPath, _ := newRetentionStore(t, DefaultConfig())
	var mode int
	s.db.QueryRow("PRAGMA auto_vacuum").Scan(&mode)
	if mode != 2 {
		t.Fatalf("fresh DB auto_vacuum = %d, want 2", mode)
	}
	payload := strings.Repeat("x", 2000)
	old := time.Now().Add(-90 * 24 * time.Hour)
	tx, _ := s.db.Begin()
	for i := 0; i < 6000; i++ {
		tx.Exec(`INSERT INTO traffic (ts,direction,server_name,method,payload) VALUES (?,?,?,?,?)`,
			old.UTC().Format(time.RFC3339Nano), "c2s", "srv", "m", payload)
	}
	tx.Commit()
	s.db.Exec("PRAGMA wal_checkpoint(TRUNCATE)")
	before := fileSize(t, dbPath)
	if before < 10<<20 {
		t.Fatalf("seeded DB unexpectedly small: %d", before)
	}
	res, err := s.Prune(context.Background())
	if err != nil || res.RowsDeleted != 6000 {
		t.Fatalf("prune: %+v %v", res, err)
	}
	after := fileSize(t, dbPath)
	if after >= before/2 {
		t.Fatalf("DB did not shrink: before=%d after=%d", before, after)
	}
	if wal := fileSize(t, dbPath+"-wal"); wal > 1<<20 {
		t.Fatalf("WAL not truncated: %d bytes", wal)
	}
}

func fileSize(t *testing.T, p string) int64 {
	t.Helper()
	fi, err := os.Stat(p)
	if err != nil {
		if os.IsNotExist(err) {
			return 0
		}
		t.Fatal(err)
	}
	return fi.Size()
}

func TestNewStore_ConvertsLegacyDBToIncrementalVacuum(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "legacy.db")
	db, err := sql.Open("sqlite3", dbPath)
	if err != nil {
		t.Fatal(err)
	}
	db.SetMaxOpenConns(1)
	if _, err := db.Exec(`PRAGMA journal_mode=WAL; CREATE TABLE traffic (
		id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, direction TEXT NOT NULL, server_name TEXT NOT NULL,
		method TEXT NOT NULL DEFAULT '', message_id TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL,
		status TEXT NOT NULL DEFAULT 'ok', latency_ms INTEGER, matched_id INTEGER);`); err != nil {
		t.Fatal(err)
	}
	var mode int
	db.QueryRow("PRAGMA auto_vacuum").Scan(&mode)
	if mode != 0 {
		t.Fatalf("legacy fixture auto_vacuum = %d, want 0 (fixture invalid)", mode)
	}
	old := time.Now().Add(-90 * 24 * time.Hour).UTC().Format(time.RFC3339Nano)
	recent := time.Now().UTC().Format(time.RFC3339Nano)
	db.Exec(`INSERT INTO traffic (ts,direction,server_name,payload) VALUES (?, 'c2s','srv','{}'), (?, 'c2s','srv','{}')`, old, recent)
	db.Close()

	cfg := DefaultConfig()
	cfg.NoBackgroundPrune = true
	s, err := NewStoreWithConfig(dbPath, filepath.Join(dir, "l.jsonl"), cfg)
	if err != nil {
		t.Fatalf("NewStoreWithConfig on legacy DB: %v", err)
	}
	defer s.Close()
	s.db.QueryRow("PRAGMA auto_vacuum").Scan(&mode)
	if mode != 2 {
		t.Fatalf("legacy DB auto_vacuum after migration = %d, want 2", mode)
	}
	if n := count(t, s, "SELECT COUNT(*) FROM traffic"); n != 1 {
		t.Fatalf("expected the expired row pruned before VACUUM and the recent row kept, got %d rows", n)
	}
}

func TestPrune_ConcurrentInsertsAreSafe_AndLoopStopsOnClose(t *testing.T) {
	dir := t.TempDir()
	cfg := DefaultConfig()
	cfg.PruneInterval = 5 * time.Millisecond // background loop active, very frequent
	s, err := NewStoreWithConfig(filepath.Join(dir, "c.db"), filepath.Join(dir, "c.jsonl"), cfg)
	if err != nil {
		t.Fatal(err)
	}
	base := runtime.NumGoroutine()
	_ = base
	// Backlog of expired rows so prune does real batched work.
	old := time.Now().Add(-90 * 24 * time.Hour).UTC().Format(time.RFC3339Nano)
	tx, _ := s.db.Begin()
	for i := 0; i < 12000; i++ {
		tx.Exec(`INSERT INTO traffic (ts,direction,server_name,method,payload) VALUES (?,?,?,?,?)`, old, "c2s", "srv", "old", "{}")
	}
	tx.Commit()

	var wg sync.WaitGroup
	for g := 0; g < 4; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			for i := 0; i < 50; i++ {
				id, _ := s.Insert(&TrafficEntry{Timestamp: time.Now(), Direction: DirectionClientToServer, ServerName: "srv",
					Method: "live", MessageID: fmt.Sprintf("%d-%d", g, i), Payload: "{}", Status: "pending"})
				if id == 0 {
					t.Errorf("insert failed during prune")
					return
				}
			}
		}(g)
	}
	// Explicit concurrent prunes as well as the background loop.
	for i := 0; i < 3; i++ {
		if _, err := s.Prune(context.Background()); err != nil {
			t.Errorf("Prune: %v", err)
		}
	}
	wg.Wait()
	if n := count(t, s, `SELECT COUNT(*) FROM traffic WHERE method='live'`); n != 200 {
		t.Fatalf("live rows = %d, want 200", n)
	}
	if n := count(t, s, `SELECT COUNT(*) FROM traffic WHERE method='old'`); n != 0 {
		t.Fatalf("old rows left: %d", n)
	}
	st, err := s.PerformanceStats()
	if err != nil || st.LastPruneAt == "" {
		t.Fatalf("PerformanceStats last prune missing: %+v %v", st, err)
	}

	if err := s.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	// After Close the prune loop must be gone (Close waits for it).
	done := make(chan struct{})
	go func() { s.pruneWG.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("prune goroutine did not exit on Close")
	}
}

func TestPerformanceStats_ReportsJSONLTotalAndLastPrune(t *testing.T) {
	s, _, jsonlPath := newRetentionStore(t, DefaultConfig())
	st, _ := s.PerformanceStats()
	if st.LastPruneAt != "" {
		t.Fatalf("LastPruneAt before any prune = %q", st.LastPruneAt)
	}
	seedTraffic(t, s, time.Now().Add(-90*24*time.Hour), nil, "x")
	s.Insert(&TrafficEntry{Timestamp: time.Now(), Direction: DirectionClientToServer, ServerName: "s", Payload: "{}", Status: "ok"})
	if _, err := s.Prune(context.Background()); err != nil {
		t.Fatal(err)
	}
	st, err := s.PerformanceStats()
	if err != nil {
		t.Fatal(err)
	}
	if st.JSONLTotalBytes != fileSize(t, jsonlPath) || st.JSONLTotalBytes == 0 {
		t.Fatalf("JSONLTotalBytes = %d, file = %d", st.JSONLTotalBytes, fileSize(t, jsonlPath))
	}
	if st.LastPruneAt == "" || st.LastPruneRowsDeleted != 1 {
		t.Fatalf("last prune = %q/%d, want set/1", st.LastPruneAt, st.LastPruneRowsDeleted)
	}
}
