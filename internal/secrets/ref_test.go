package secrets

import "testing"

func TestParseSecretRef(t *testing.T) {
	cases := []struct {
		input string
		want  refKind
	}{
		{"@keychain:my-service/my-account", refKeychain},
		{"op://vault/item/field", refOP},
		{"${MY_VAR}", refEnv},
		{"plain-value", refPlain},
		{"", refPlain},
		{"${}", refEnv},                       // minimal env ref
		{"${NESTED", refPlain},                // missing closing brace → plain
		{"op://", refOP},                      // minimal op ref
		{"@keychain:", refKeychain},           // minimal keychain ref
		{"https://example.com", refPlain},     // URL is plain
	}

	for _, tc := range cases {
		got := parseSecretRef(tc.input)
		if got != tc.want {
			t.Errorf("parseSecretRef(%q) = %d, want %d", tc.input, got, tc.want)
		}
	}
}
