//go:build darwin

package keychain

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strings"
)

// Typed errors for known macOS Keychain exit codes.
var (
	ErrKeychainNotFound  = errors.New("keychain: item not found")
	ErrKeychainCancelled = errors.New("keychain: user cancelled")
	ErrKeychainHeadless  = errors.New("keychain: no GUI available (headless)")
)

// Resolver resolves @keychain:service/account references via the macOS
// `security find-generic-password` CLI.
type Resolver struct{}

// CanResolve returns true when ref starts with "@keychain:".
func (r *Resolver) CanResolve(ref string) bool {
	return strings.HasPrefix(ref, "@keychain:")
}

// Resolve runs `security find-generic-password -a <account> -s <service> -w`
// and returns the trimmed secret on success.
// The returned value is never logged — only the key name and errors are logged.
func (r *Resolver) Resolve(ctx context.Context, ref string) (string, error) {
	svc, acct, err := parseRef(ref)
	if err != nil {
		return "", err
	}

	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, "security", "find-generic-password",
		"-a", acct,
		"-s", svc,
		"-w",
	)
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	runErr := cmd.Run()
	if runErr == nil {
		// Success — return trimmed value, never log it
		return strings.TrimRight(stdout.String(), "\n"), nil
	}

	// Map exit codes to typed errors
	var exitErr *exec.ExitError
	if errors.As(runErr, &exitErr) {
		switch exitErr.ExitCode() {
		case 44:
			return "", ErrKeychainNotFound
		case 36:
			return "", ErrKeychainCancelled
		case 51:
			return "", ErrKeychainHeadless
		}
	}

	// Generic error — include stderr but never the resolved value
	msg := strings.TrimSpace(stderr.String())
	if msg == "" {
		msg = runErr.Error()
	}
	return "", fmt.Errorf("keychain: %s", msg)
}

// parseRef splits "@keychain:service/account" into (service, account).
func parseRef(ref string) (svc, acct string, err error) {
	// Strip "@keychain:" prefix
	rest := strings.TrimPrefix(ref, "@keychain:")
	idx := strings.Index(rest, "/")
	if idx < 0 {
		return "", "", fmt.Errorf("keychain: malformed ref %q — expected @keychain:service/account", ref)
	}
	return rest[:idx], rest[idx+1:], nil
}
