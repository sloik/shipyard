package env

import (
	"context"
	"os"
	"strings"
)

// Resolver resolves ${VAR_NAME} references via os.Getenv.
// Consistent with shell semantics: an unset variable resolves to "" without error.
type Resolver struct{}

// CanResolve returns true when ref has the form ${...}.
func (r *Resolver) CanResolve(ref string) bool {
	return strings.HasPrefix(ref, "${") && strings.HasSuffix(ref, "}")
}

// Resolve extracts the variable name from ${VAR_NAME} and returns its value.
// Returns "" (no error) when the variable is not set, consistent with shell behavior.
// The returned value is never logged.
func (r *Resolver) Resolve(_ context.Context, ref string) (string, error) {
	// Strip ${ prefix and } suffix
	name := ref[2 : len(ref)-1]
	return os.Getenv(name), nil
}
