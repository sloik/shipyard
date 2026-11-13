package capture

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func rotStore(t *testing.T, max int64, keep int) (*Store, string) {
	t.Helper()
	dir := t.TempDir()
	cfg := DefaultConfig()
	cfg.JSONLMaxBytes = max
	cfg.JSONLKeep = keep
	cfg.NoBackgroundPrune = true
	p := filepath.Join(dir, "x.jsonl")
	s, err := NewStoreWithConfig(filepath.Join(dir, "x.db"), p, cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s, p
}

func TestJSONLRotation_KeepsExactlyKeepFiles(t *testing.T) {
	const max = 1024
	s, p := rotStore(t, max, 3)
	var lastMarker string
	for i := 0; i < 200; i++ {
		lastMarker = fmt.Sprintf("marker-%04d", i)
		s.Insert(&TrafficEntry{Timestamp: time.Now(), Direction: DirectionClientToServer, ServerName: "srv",
			Method: lastMarker, Payload: strings.Repeat("p", 60), Status: "ok"})
	}
	for i := 1; i <= 3; i++ {
		if _, err := os.Stat(fmt.Sprintf("%s.%d", p, i)); err != nil {
			t.Fatalf(".%d missing: %v", i, err)
		}
	}
	if _, err := os.Stat(p + ".4"); !os.IsNotExist(err) {
		t.Fatalf(".4 must not exist (err=%v)", err)
	}
	files := []string{p, p + ".1", p + ".2", p + ".3"}
	for _, f := range files {
		fi, _ := os.Stat(f)
		// every file ≤ max (one entry ~ 250B so rotation happens before exceeding max)
		if fi.Size() > max {
			t.Fatalf("%s is %d bytes > max %d", f, fi.Size(), max)
		}
	}
	cur, _ := os.ReadFile(p)
	if !bytes.Contains(cur, []byte(lastMarker)) {
		t.Fatalf("newest entry %s not in current file", lastMarker)
	}
	st, _ := s.PerformanceStats()
	var sum int64
	for _, f := range files {
		fi, _ := os.Stat(f)
		sum += fi.Size()
	}
	if st.JSONLTotalBytes != sum {
		t.Fatalf("JSONLTotalBytes %d != sum %d", st.JSONLTotalBytes, sum)
	}
}

func TestJSONLRotation_OversizedLegacyFileIsTrimmedNotKept(t *testing.T) {
	const max = 1000
	dir := t.TempDir()
	p := filepath.Join(dir, "legacy.jsonl")
	var b bytes.Buffer
	for i := 0; b.Len() < 10*max; i++ {
		fmt.Fprintf(&b, "{\"line\":%06d,\"pad\":\"%s\"}\n", i, strings.Repeat("z", 40))
	}
	if err := os.WriteFile(p, b.Bytes(), 0644); err != nil {
		t.Fatal(err)
	}
	cfg := DefaultConfig()
	cfg.JSONLMaxBytes = max
	cfg.NoBackgroundPrune = true
	s, err := NewStoreWithConfig(filepath.Join(dir, "l.db"), p, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()

	got, _ := os.ReadFile(p)
	if int64(len(got)) > max || len(got) == 0 {
		t.Fatalf("trimmed size %d, want 0 < size <= %d", len(got), max)
	}
	if got[0] != '{' || !bytes.HasSuffix(got, []byte("}\n")) {
		t.Fatalf("tail must start and end on line boundaries: %q ... %q", got[:5], got[len(got)-5:])
	}
	if !bytes.HasSuffix(b.Bytes(), got) {
		t.Fatal("kept bytes are not the tail of the original file")
	}
	if _, err := os.Stat(p + ".1"); !os.IsNotExist(err) {
		t.Fatalf("legacy file must not survive as .1 (err=%v)", err)
	}
	if st, _ := s.PerformanceStats(); st.JSONLTotalBytes > 4*max {
		t.Fatalf("total %d > (keep+1)*max", st.JSONLTotalBytes)
	}
	if _, err := os.Stat(p + ".trim.tmp"); !os.IsNotExist(err) {
		t.Fatal("temp file left behind")
	}
}

func TestJSONLRotation_DisabledWhenMaxNonPositive(t *testing.T) {
	for _, max := range []int64{0, -1} {
		s, p := rotStore(t, max, 3)
		for i := 0; i < 50; i++ {
			s.Insert(&TrafficEntry{Timestamp: time.Now(), Direction: DirectionClientToServer, ServerName: "srv", Payload: strings.Repeat("p", 100), Status: "ok"})
		}
		if _, err := os.Stat(p + ".1"); !os.IsNotExist(err) {
			t.Fatalf("max=%d must not rotate (err=%v)", max, err)
		}
	}
}

func TestJSONLRotation_StaleRotatedFilesBeyondKeepAreRemoved(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "s.jsonl")
	for i := 1; i <= 5; i++ {
		os.WriteFile(fmt.Sprintf("%s.%d", p, i), []byte("x\n"), 0644)
	}
	cfg := DefaultConfig()
	cfg.JSONLKeep = 2
	cfg.NoBackgroundPrune = true
	s, err := NewStoreWithConfig(filepath.Join(dir, "s.db"), p, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	for i := 3; i <= 5; i++ {
		if _, err := os.Stat(fmt.Sprintf("%s.%d", p, i)); !os.IsNotExist(err) {
			t.Fatalf(".%d should have been removed", i)
		}
	}
}
