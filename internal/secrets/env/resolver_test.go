package env

import (
	"context"
	"os"
	"testing"
)

func TestEnvResolver_CanResolve(t *testing.T) {
	r := &Resolver{}
	cases := []struct {
		ref  string
		want bool
	}{
		{"${MY_VAR}", true},
		{"${ANOTHER_VAR}", true},
		{"${}", true},
		{"plain-value", false},
		{"op://vault/item", false},
		{"@keychain:svc/acct", false},
		{"${MISSING_CLOSE", false},
	}
	for _, tc := range cases {
		got := r.CanResolve(tc.ref)
		if got != tc.want {
			t.Errorf("CanResolve(%q) = %v, want %v", tc.ref, got, tc.want)
		}
	}
}

func TestEnvResolver_Resolve(t *testing.T) {
	r := &Resolver{}
	ctx := context.Background()

	// Set a test variable
	const key = "SHIPYARD_TEST_SECRET_VAR"
	os.Setenv(key, "test-secret-value")
	defer os.Unsetenv(key)

	got, err := r.Resolve(ctx, "${"+key+"}")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "test-secret-value" {
		t.Errorf("Resolve returned %q, want %q", got, "test-secret-value")
	}
}

func TestEnvResolver_Resolve_Unset(t *testing.T) {
	r := &Resolver{}
	ctx := context.Background()

	// Ensure the variable is definitely not set
	const key = "SHIPYARD_TEST_DEFINITELY_NOT_SET_VARIABLE_XYZ"
	os.Unsetenv(key)

	got, err := r.Resolve(ctx, "${"+key+"}")
	if err != nil {
		t.Fatalf("unexpected error for unset var: %v", err)
	}
	if got != "" {
		t.Errorf("Resolve of unset var returned %q, want empty string", got)
	}
}
