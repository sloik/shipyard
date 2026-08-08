package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func FuzzConfigDecodeRoundTrip(f *testing.F) {
	for _, seed := range []string{
		``, `null`, `{"servers":`, `{"servers":{}}`,
		`{"servers":{"alpha":{"command":"echo","args":["hello"]}},"web":{"port":9417}}`,
		`{"servers":{"α":{"command":"echo"}},"unknown":{"duplicate":true},"web":{"port":999999}}`,
		`{"servers":{"alpha":{"command":"first"},"alpha":{"command":"second"}}`,
		`{"servers":{"nested":{"command":"echo","args":[[[[["boundary"]]]]]}}}`,
	} {
		f.Add(seed)
	}

	f.Fuzz(func(t *testing.T, raw string) {
		if len(raw) > 64*1024 {
			t.Skip()
		}

		var cfg Config
		err := json.Unmarshal([]byte(raw), &cfg)
		if err != nil {
			return
		}
		if cfg.Servers == nil {
			// A missing or null servers member intentionally leaves the config at
			// its zero-value defaults; Config's custom decoder only accepts an
			// object when the member is present.
			return
		}

		encoded, err := json.Marshal(cfg)
		if err != nil {
			t.Fatalf("marshal decoded config: %v", err)
		}
		var roundTrip Config
		if err := json.Unmarshal(encoded, &roundTrip); err != nil {
			t.Fatalf("decode round-trip config: %v", err)
		}
		if len(roundTrip.Servers) != len(cfg.Servers) {
			t.Fatalf("server count changed after round trip: got %d, want %d", len(roundTrip.Servers), len(cfg.Servers))
		}
		for _, name := range cfg.ServerOrder {
			if _, ok := cfg.Servers[name]; !ok {
				t.Fatalf("server order contains unknown server %q", name)
			}
		}
		if strings.Contains(raw, `"servers":null`) && cfg.Servers != nil {
			t.Fatalf("null servers must not decode as a populated server map")
		}
	})
}
