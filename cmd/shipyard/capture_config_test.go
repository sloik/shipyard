package main

import (
	"encoding/json"
	"testing"
	"time"
)

func TestCaptureConfig_DefaultsWhenAbsent(t *testing.T) {
	var cfg Config
	if err := json.Unmarshal([]byte(`{"servers":{}}`), &cfg); err != nil {
		t.Fatal(err)
	}
	got := cfg.Capture.resolve()
	if got.RetentionDays != 60 || got.PruneInterval != 6*time.Hour || got.JSONLMaxBytes != 100*1024*1024 || got.JSONLKeep != 3 {
		t.Fatalf("defaults = %+v", got)
	}
}

func TestCaptureConfig_OverridesAndZeroDisables(t *testing.T) {
	var cfg Config
	raw := `{"capture":{"retention_days":0,"prune_interval_hours":1,"jsonl_max_bytes":-1,"jsonl_keep":5}}`
	if err := json.Unmarshal([]byte(raw), &cfg); err != nil {
		t.Fatal(err)
	}
	got := cfg.Capture.resolve()
	if got.RetentionDays != 0 || got.PruneInterval != time.Hour || got.JSONLMaxBytes != -1 || got.JSONLKeep != 5 {
		t.Fatalf("resolved = %+v", got)
	}
}
