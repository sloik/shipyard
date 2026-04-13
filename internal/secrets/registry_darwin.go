//go:build darwin

package secrets

import "github.com/sloik/shipyard/internal/secrets/keychain"

// addKeychainResolver registers the darwin Keychain resolver.
func addKeychainResolver(reg *Registry) {
	reg.Register(&keychain.Resolver{})
}
