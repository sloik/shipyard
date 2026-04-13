package auth

import (
	"sync"
	"time"
)

// RateLimiter is an in-memory, per-token sliding window rate limiter.
// Counters are keyed by token ID and reset after each 1-minute window.
// A restart clears all counters — that is acceptable per spec.
type RateLimiter struct {
	mu      sync.Mutex
	windows map[int64]*tokenWindow
}

type tokenWindow struct {
	count     int
	windowStart time.Time
}

// NewRateLimiter creates a ready-to-use RateLimiter.
func NewRateLimiter() *RateLimiter {
	return &RateLimiter{
		windows: make(map[int64]*tokenWindow),
	}
}

// Allow reports whether a call by the token with the given ID is permitted.
// A limitPerMin of 0 means unlimited.
// It increments the counter if the call is allowed.
func (r *RateLimiter) Allow(tokenID int64, limitPerMin int) bool {
	if limitPerMin <= 0 {
		return true
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	now := time.Now()
	w, ok := r.windows[tokenID]
	if !ok || now.Sub(w.windowStart) >= time.Minute {
		// New or expired window
		r.windows[tokenID] = &tokenWindow{count: 1, windowStart: now}
		return true
	}

	if w.count >= limitPerMin {
		return false
	}
	w.count++
	return true
}
