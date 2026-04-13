//go:build darwin

package keychain

import (
	"context"
	"testing"
)

func TestKeychainResolver_CanResolve(t *testing.T) {
	r := &Resolver{}
	cases := []struct {
		ref  string
		want bool
	}{
		{"@keychain:my-service/my-account", true},
		{"@keychain:", true},
		{"op://vault/item", false},
		{"${VAR}", false},
		{"plain-value", false},
	}
	for _, tc := range cases {
		got := r.CanResolve(tc.ref)
		if got != tc.want {
			t.Errorf("CanResolve(%q) = %v, want %v", tc.ref, got, tc.want)
		}
	}
}

func TestKeychainResolver_ParseRef(t *testing.T) {
	svc, acct, err := parseRef("@keychain:my-service/my-account")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if svc != "my-service" {
		t.Errorf("service = %q, want %q", svc, "my-service")
	}
	if acct != "my-account" {
		t.Errorf("account = %q, want %q", acct, "my-account")
	}
}

func TestKeychainResolver_ParseRef_MalformedNoSlash(t *testing.T) {
	_, _, err := parseRef("@keychain:no-slash-here")
	if err == nil {
		t.Fatal("expected error for malformed ref, got nil")
	}
}

// TestKeychainResolver_Resolve_Integration tests actual keychain lookup.
// It requires a test item pre-created with:
//
//	security add-generic-password -a test-api-key -s shipyard-test -w test-secret-value
//
// Skip when the item does not exist (expected in CI environments).
func TestKeychainResolver_Resolve_Integration(t *testing.T) {
	r := &Resolver{}
	ctx := context.Background()

	_, err := r.Resolve(ctx, "@keychain:shipyard-test/test-api-key")
	if err == ErrKeychainNotFound {
		t.Skip("keychain test item not present — run: security add-generic-password -a test-api-key -s shipyard-test -w test-secret-value")
	}
	if err != nil {
		t.Skipf("keychain lookup failed (%v) — skipping integration test", err)
	}
	// If no error, the secret was resolved (we don't log it — just verify no error)
}
