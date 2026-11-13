package capture

import "time"

// Default retention and rotation limits (SPEC-SHIPYD-001).
const (
	DefaultRetentionDays = 60
	DefaultPruneInterval = 6 * time.Hour
	DefaultJSONLMaxBytes = 100 * 1024 * 1024
	DefaultJSONLKeep     = 3

	// pruneBatchSize bounds the rows deleted per transaction so the
	// single-connection store never starves capture inserts for long.
	pruneBatchSize = 5000
	// vacuumChunkPages bounds the pages released per incremental_vacuum call.
	vacuumChunkPages = 2000
)

// Config holds the capture-store retention and rotation limits.
//
// For every field, 0 or a negative value disables that limit:
//   - RetentionDays <= 0: traffic rows are never pruned by age.
//   - PruneInterval <= 0: no periodic prune (the startup prune still runs
//     when RetentionDays > 0).
//   - JSONLMaxBytes <= 0: the JSONL backup is never rotated.
//   - JSONLKeep <= 0: rotation keeps no rotated files (the full file is
//     discarded when it reaches JSONLMaxBytes).
type Config struct {
	RetentionDays int
	PruneInterval time.Duration
	JSONLMaxBytes int64
	JSONLKeep     int

	// NoBackgroundPrune disables the startup/periodic prune goroutine. Prune
	// can still be called explicitly. Intended for tests.
	NoBackgroundPrune bool
}

// DefaultConfig returns the policy defaults: 60d retention, prune every 6h,
// JSONL rotated at 100 MB keeping 3 files.
func DefaultConfig() Config {
	return Config{
		RetentionDays: DefaultRetentionDays,
		PruneInterval: DefaultPruneInterval,
		JSONLMaxBytes: DefaultJSONLMaxBytes,
		JSONLKeep:     DefaultJSONLKeep,
	}
}
