package main

import (
	"context"
	"errors"
	"testing"

	"github.com/sloik/shipyard/internal/secrets"
)

// mockResolver is a test-only SecretResolver that returns configured responses.
type mockResolver struct {
	// canResolveKeys is the set of keys (refs) this resolver claims to handle.
	canResolveKeys map[string]bool
	// resolveMap maps ref → resolved value.
	resolveMap map[string]string
	// resolveErr maps ref → error to return on Resolve.
	resolveErr map[string]error
}

func (m *mockResolver) CanResolve(ref string) bool {
	return m.canResolveKeys[ref]
}

func (m *mockResolver) Resolve(_ context.Context, ref string) (string, error) {
	if err, ok := m.resolveErr[ref]; ok {
		return "", err
	}
	if v, ok := m.resolveMap[ref]; ok {
		return v, nil
	}
	return ref, nil
}

// newMockRegistry builds a Registry backed by the given mockResolver.
func newMockRegistry(r *mockResolver) *secrets.Registry {
	reg := &secrets.Registry{}
	reg.Register(r)
	return reg
}

// TestResolveEnv_PlainPassthrough verifies that a plain-text value (no secret
// reference prefix) passes through the registry unchanged.
func TestResolveEnv_PlainPassthrough(t *testing.T) {
	reg := &secrets.Registry{} // empty registry — no resolvers registered
	env := map[string]string{
		"PLAIN_KEY": "plain-value",
	}

	got := resolveEnv(context.Background(), env, reg)

	if len(got) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(got))
	}
	if got["PLAIN_KEY"] != "plain-value" {
		t.Errorf("PLAIN_KEY: got %q, want %q", got["PLAIN_KEY"], "plain-value")
	}
	// Original map must not be mutated.
	if env["PLAIN_KEY"] != "plain-value" {
		t.Error("original env map was mutated")
	}
}

// TestResolveEnv_ErrorIsNonFatal verifies that a resolution error on one key
// does not prevent other keys from resolving, and the errored key falls back
// to its original reference string.
func TestResolveEnv_ErrorIsNonFatal(t *testing.T) {
	bad := "@keychain:missing-key"
	good := "@keychain:good-key"

	resolver := &mockResolver{
		canResolveKeys: map[string]bool{bad: true, good: true},
		resolveMap:     map[string]string{good: "resolved-good-value"},
		resolveErr:     map[string]error{bad: errors.New("keychain item not found")},
	}
	reg := newMockRegistry(resolver)

	env := map[string]string{
		"BAD_KEY":  bad,
		"GOOD_KEY": good,
	}

	got := resolveEnv(context.Background(), env, reg)

	if len(got) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(got))
	}
	// BAD_KEY falls back to original ref.
	if got["BAD_KEY"] != bad {
		t.Errorf("BAD_KEY: got %q, want original ref %q", got["BAD_KEY"], bad)
	}
	// GOOD_KEY is resolved.
	if got["GOOD_KEY"] != "resolved-good-value" {
		t.Errorf("GOOD_KEY: got %q, want %q", got["GOOD_KEY"], "resolved-good-value")
	}
	// Original env must not be mutated.
	if env["BAD_KEY"] != bad {
		t.Error("original env map was mutated for BAD_KEY")
	}
	if env["GOOD_KEY"] != good {
		t.Error("original env map was mutated for GOOD_KEY")
	}
}

// TestResolveEnv_NilEnv verifies that resolveEnv handles nil env maps safely.
func TestResolveEnv_NilEnv(t *testing.T) {
	reg := &secrets.Registry{}
	got := resolveEnv(context.Background(), nil, reg)
	if len(got) != 0 {
		t.Errorf("expected empty map for nil input, got %v", got)
	}
}
