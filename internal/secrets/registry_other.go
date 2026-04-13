//go:build !darwin

package secrets

// addKeychainResolver is a no-op on non-darwin platforms.
func addKeychainResolver(_ *Registry) {}
