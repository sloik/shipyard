package capture

import (
	"math"
	"math/bits"
)

// Size arithmetic for the retention code (BUG-SHIPYD-004). SQLite PRAGMA
// results and statfs fields are signed on some platforms; converting a
// negative value straight to uint64 yields a number near 2^64, which made the
// free-space check fail forever. Everything here clamps at 0 and saturates at
// math.MaxUint64 instead of wrapping.

// sizeInt covers the integer types statfs fields and SQLite counters use
// across platforms.
type sizeInt interface {
	~int | ~int32 | ~int64 | ~uint | ~uint32 | ~uint64
}

// clampUint64 converts v to uint64, mapping negative values to 0.
func clampUint64[T sizeInt](v T) uint64 {
	if v < 0 {
		return 0
	}
	return uint64(v)
}

// mulSaturating returns a*b, or math.MaxUint64 when the product overflows.
func mulSaturating(a, b uint64) uint64 {
	hi, lo := bits.Mul64(a, b)
	if hi != 0 {
		return math.MaxUint64
	}
	return lo
}

// liveDBBytes returns the bytes held by non-free pages of a SQLite database.
// It returns 0 when any input is negative or when no page is live.
func liveDBBytes(pageCount, freePages, pageSize int64) uint64 {
	if pageCount <= 0 || freePages < 0 || pageSize <= 0 || freePages >= pageCount {
		return 0
	}
	return mulSaturating(clampUint64(pageCount-freePages), clampUint64(pageSize))
}

// blocksToBytes returns blocks*bsize, treating a negative operand as 0.
func blocksToBytes[B, S sizeInt](blocks B, bsize S) uint64 {
	return mulSaturating(clampUint64(blocks), clampUint64(bsize))
}
