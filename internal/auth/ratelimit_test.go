package auth

import (
	"testing"
	"time"
)

// AC-13: Token with rate_limit_per_minute: 60 → 61st request in one minute → denied.
func TestRateLimiter_AllowsUpToLimit(t *testing.T) {
	r := NewRateLimiter()

	const limit = 5
	const tokenID = int64(42)

	for i := 0; i < limit; i++ {
		if !r.Allow(tokenID, limit) {
			t.Fatalf("call %d should be allowed (limit %d)", i+1, limit)
		}
	}

	// 6th call must be denied
	if r.Allow(tokenID, limit) {
		t.Fatal("call beyond limit should be denied")
	}
}

// AC-14: Rate limit counter resets after the minute window expires.
func TestRateLimiter_ResetsAfterWindow(t *testing.T) {
	r := NewRateLimiter()
	const tokenID = int64(99)
	const limit = 2

	r.Allow(tokenID, limit)
	r.Allow(tokenID, limit)

	// Exhaust limit
	if r.Allow(tokenID, limit) {
		t.Fatal("3rd call should be denied")
	}

	// Force window expiry
	r.mu.Lock()
	r.windows[tokenID].windowStart = time.Now().Add(-2 * time.Minute)
	r.mu.Unlock()

	// Should allow again after window reset
	if !r.Allow(tokenID, limit) {
		t.Fatal("should allow after window reset")
	}
}

// No limit (0) means unlimited.
func TestRateLimiter_ZeroLimitUnlimited(t *testing.T) {
	r := NewRateLimiter()
	const tokenID = int64(1)

	for i := 0; i < 1000; i++ {
		if !r.Allow(tokenID, 0) {
			t.Fatal("zero limit should always allow")
		}
	}
}

// Different tokens have independent counters.
func TestRateLimiter_IsolatedPerToken(t *testing.T) {
	r := NewRateLimiter()
	const limit = 2

	r.Allow(1, limit)
	r.Allow(1, limit)
	// Token 1 exhausted

	// Token 2 is independent
	if !r.Allow(2, limit) {
		t.Fatal("token 2 should have its own window")
	}
}
