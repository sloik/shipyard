package secrets

import (
	"context"

	envresolver "github.com/sloik/shipyard/internal/secrets/env"
	"github.com/sloik/shipyard/internal/secrets/op"
)

// Registry holds an ordered list of SecretResolvers.
// Resolvers are tried in registration order; the first one whose CanResolve
// returns true handles the ref. When no resolver claims the ref, the original
// string is returned unchanged (plain-text fallback).
type Registry struct {
	resolvers []SecretResolver
}

// Register appends r to the resolver chain.
func (reg *Registry) Register(r SecretResolver) {
	reg.resolvers = append(reg.resolvers, r)
}

// Resolve tries each registered resolver in order.
// The first resolver whose CanResolve returns true handles ref.
// If no resolver matches, ref is returned unchanged (plain-text fallback).
// The returned value must never be passed to any logger.
func (reg *Registry) Resolve(ctx context.Context, ref string) (string, error) {
	for _, r := range reg.resolvers {
		if r.CanResolve(ref) {
			return r.Resolve(ctx, ref)
		}
	}
	// No resolver matched — return ref as-is (plain-text passthrough)
	return ref, nil
}

// DefaultRegistry builds a Registry with resolvers appropriate for backend.
//
// Supported backend values:
//   - "keychain" → Keychain resolver + env resolver (darwin only; env only on other platforms)
//   - "1password" → OP resolver + env resolver
//   - "env"       → env resolver only
//   - ""          → auto: all available resolvers (Keychain if darwin, OP if in PATH, always env)
//
// The plain-text fallback is built into Registry.Resolve — not a registered resolver.
func DefaultRegistry(backend string) *Registry {
	reg := &Registry{}

	switch backend {
	case "keychain":
		addKeychainIfDarwin(reg)
		reg.Register(&envresolver.Resolver{})

	case "1password":
		reg.Register(&op.Resolver{})
		reg.Register(&envresolver.Resolver{})

	case "env":
		reg.Register(&envresolver.Resolver{})

	default: // "" → auto
		addKeychainIfDarwin(reg)
		reg.Register(&op.Resolver{})
		reg.Register(&envresolver.Resolver{})
	}

	return reg
}

// addKeychainIfDarwin delegates to the platform-specific addKeychainResolver.
// Defined in registry_darwin.go (registers Keychain) and registry_other.go (no-op).
func addKeychainIfDarwin(reg *Registry) {
	addKeychainResolver(reg)
}
