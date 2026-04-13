package secrets

import "strings"

// refKind identifies the type of a secret reference string.
type refKind int

const (
	refPlain    refKind = iota // plain text value — no resolution needed
	refKeychain                // @keychain:service/account
	refOP                      // op://vault/item/field
	refEnv                     // ${VAR_NAME}
)

// parseSecretRef classifies a reference string into its refKind.
func parseSecretRef(s string) refKind {
	switch {
	case strings.HasPrefix(s, "@keychain:"):
		return refKeychain
	case strings.HasPrefix(s, "op://"):
		return refOP
	case strings.HasPrefix(s, "${") && strings.HasSuffix(s, "}"):
		return refEnv
	default:
		return refPlain
	}
}
