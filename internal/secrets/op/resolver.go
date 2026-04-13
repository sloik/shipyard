package op

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
)

// Resolver resolves op:// references via the 1Password CLI (`op read`).
// If the `op` binary is not in PATH, CanResolve returns false.
type Resolver struct{}

// CanResolve returns true when ref starts with "op://" AND the `op` binary is in PATH.
func (r *Resolver) CanResolve(ref string) bool {
	if !strings.HasPrefix(ref, "op://") {
		return false
	}
	_, err := exec.LookPath("op")
	return err == nil
}

// Resolve runs `op read <ref>` and returns the trimmed secret on success.
// On failure, returns the stderr message as error — never the resolved value.
func (r *Resolver) Resolve(ctx context.Context, ref string) (string, error) {
	var stdout, stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, "op", "read", ref)
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		// Never include the ref value or any resolved secret in the error
		return "", fmt.Errorf("op: %s", msg)
	}

	return strings.TrimRight(stdout.String(), "\n"), nil
}
