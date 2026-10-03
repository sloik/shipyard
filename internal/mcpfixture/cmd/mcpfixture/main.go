// Command mcpfixture runs Shipyard's MCP fixture server or fixture client for
// the official conformance CLI (scripts/mcp-conformance.sh). Stub.
package main

import (
	"bytes"
	"context"
	"io"
	"sync"
)

func main() {}

func run(context.Context, []string, func(string) string, io.Writer) error { return nil }

type lockedBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *lockedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *lockedBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}
