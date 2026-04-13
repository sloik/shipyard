package op

import (
	"os/exec"
	"testing"
)

func TestOPResolver_CanResolve(t *testing.T) {
	r := &Resolver{}

	// Non-op refs must always return false regardless of PATH
	cases := []struct {
		ref  string
		want bool
	}{
		{"plain-value", false},
		{"${VAR}", false},
		{"@keychain:svc/acct", false},
		{"https://example.com", false},
	}
	for _, tc := range cases {
		if got := r.CanResolve(tc.ref); got != tc.want {
			t.Errorf("CanResolve(%q) = %v, want %v", tc.ref, got, tc.want)
		}
	}
}

func TestOPResolver_CanResolve_OpPrefix(t *testing.T) {
	r := &Resolver{}
	ref := "op://vault/item/field"

	_, opInPath := exec.LookPath("op")
	want := opInPath == nil // true only when `op` is available

	got := r.CanResolve(ref)
	if got != want {
		t.Errorf("CanResolve(%q) = %v, want %v (op in PATH: %v)", ref, got, want, opInPath == nil)
	}
}

func TestOPResolver_CanResolve_NotInPath(t *testing.T) {
	// Simulate the case where op is not in PATH by checking directly.
	// If `op` is actually absent, CanResolve must return false.
	_, err := exec.LookPath("op")
	if err == nil {
		t.Skip("op binary is present in PATH — skipping 'not in PATH' test")
	}

	r := &Resolver{}
	if r.CanResolve("op://vault/item/field") {
		t.Error("CanResolve should return false when op is not in PATH")
	}
}
