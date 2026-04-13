package secrets

import "os"

// resolveEnv expands a single ${VAR_NAME} reference via os.Getenv.
// Returns the variable value, or "" if the variable is unset.
// This helper is used by SPEC-038-002 when integrating the registry into main.go.
// The returned value must never be passed to any logger.
func resolveEnv(ref string) string {
	if parseSecretRef(ref) != refEnv {
		return ref
	}
	// Strip ${ prefix and } suffix
	name := ref[2 : len(ref)-1]
	return os.Getenv(name)
}
