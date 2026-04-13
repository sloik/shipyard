package secrets

import "context"

// SecretResolver resolves secret references to their plaintext values.
// Implementations must not log resolved values at any level.
type SecretResolver interface {
	// CanResolve returns true when this resolver knows how to handle ref.
	CanResolve(ref string) bool

	// Resolve returns the plaintext secret for ref.
	// The returned string must never be passed to any logger.
	Resolve(ctx context.Context, ref string) (string, error)
}
