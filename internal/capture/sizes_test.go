package capture

import (
	"math"
	"testing"
)

// BUG-SHIPYD-004: size arithmetic must never turn a negative value into a
// huge uint64.

func TestBUGSHIPYD004_LiveDBBytes(t *testing.T) {
	tests := []struct {
		name                           string
		pageCount, freePages, pageSize int64
		want                           uint64
	}{
		{"normal", 1000, 200, 4096, 800 * 4096},
		{"no free pages", 10, 0, 4096, 10 * 4096},
		{"all zero (failed PRAGMA scans)", 0, 0, 0, 0},
		{"all pages free", 50, 50, 4096, 0},
		{"freelist above page count", 10, 11, 4096, 0},
		{"negative page count", -1, 0, 4096, 0},
		{"negative free pages", 10, -5, 4096, 0},
		{"negative page size", 10, 0, -4096, 0},
		{"zero page size", 10, 0, 0, 0},
		{"product would overflow int64", math.MaxInt64, 0, 65536, math.MaxUint64},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := liveDBBytes(tt.pageCount, tt.freePages, tt.pageSize); got != tt.want {
				t.Fatalf("liveDBBytes(%d, %d, %d) = %d, want %d",
					tt.pageCount, tt.freePages, tt.pageSize, got, tt.want)
			}
		})
	}
}

func TestBUGSHIPYD004_BlocksToBytes(t *testing.T) {
	tests := []struct {
		name          string
		blocks, bsize int64
		want          uint64
	}{
		{"normal", 1 << 20, 4096, (1 << 20) * 4096},
		{"zero blocks", 0, 4096, 0},
		{"negative block size", 100, -4096, 0},
		{"negative block count", -100, 4096, 0},
		{"product would overflow", math.MaxInt64, 65536, math.MaxUint64},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := blocksToBytes(tt.blocks, tt.bsize); got != tt.want {
				t.Fatalf("blocksToBytes(%d, %d) = %d, want %d", tt.blocks, tt.bsize, got, tt.want)
			}
		})
	}
}
