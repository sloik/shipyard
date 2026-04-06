package web

import (
	"os"
	"path/filepath"
	"testing"
)

func TestScanClaudeCode_ValidConfig(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settings.json")
	data := `{
		"mcpServers": {
			"my-server": {
				"command": "node",
				"args": ["server.js"],
				"env": {"PORT": "3000"}
			},
			"another": {
				"command": "python",
				"args": ["-m", "mcp"]
			}
		}
	}`
	if err := os.WriteFile(path, []byte(data), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	result := scanClaudeCode(path, map[string]bool{})
	if len(result) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(result))
	}

	found := map[string]bool{}
	for _, s := range result {
		found[s.Name] = true
		if s.Source != "claude-code" {
			t.Fatalf("expected source claude-code, got %q", s.Source)
		}
		if s.Status != "new" {
			t.Fatalf("expected status new, got %q", s.Status)
		}
	}
	if !found["my-server"] || !found["another"] {
		t.Fatalf("expected my-server and another, got %v", found)
	}
}

func TestScanClaudeCode_ExistingServer(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settings.json")
	data := `{
		"mcpServers": {
			"existing": {"command": "node", "args": ["server.js"]},
			"new-one": {"command": "python", "args": ["mcp.py"]}
		}
	}`
	if err := os.WriteFile(path, []byte(data), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	existing := map[string]bool{"existing": true}
	result := scanClaudeCode(path, existing)

	if len(result) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(result))
	}

	for _, s := range result {
		if s.Name == "existing" && s.Status != "already_imported" {
			t.Fatalf("expected existing server to be already_imported, got %q", s.Status)
		}
		if s.Name == "new-one" && s.Status != "new" {
			t.Fatalf("expected new server to be new, got %q", s.Status)
		}
	}
}

func TestScanClaudeCode_MissingFile(t *testing.T) {
	result := scanClaudeCode("/nonexistent/settings.json", map[string]bool{})
	if result != nil {
		t.Fatalf("expected nil for missing file, got %v", result)
	}
}

func TestScanClaudeCode_InvalidJSON(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settings.json")
	if err := os.WriteFile(path, []byte(`not json`), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	result := scanClaudeCode(path, map[string]bool{})
	if result != nil {
		t.Fatalf("expected nil for invalid JSON, got %v", result)
	}
}

func TestScanClaudeCode_EmptyCommand(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settings.json")
	data := `{
		"mcpServers": {
			"no-cmd": {"command": ""},
			"has-cmd": {"command": "node", "args": ["server.js"]}
		}
	}`
	if err := os.WriteFile(path, []byte(data), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	result := scanClaudeCode(path, map[string]bool{})
	if len(result) != 1 {
		t.Fatalf("expected 1 server (skip empty command), got %d", len(result))
	}
	if result[0].Name != "has-cmd" {
		t.Fatalf("expected has-cmd, got %q", result[0].Name)
	}
}

func TestScanClaudeDesktop_ValidConfig(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "claude_desktop_config.json")
	data := `{
		"mcpServers": {
			"desktop-srv": {
				"command": "npx",
				"args": ["-y", "@modelcontextprotocol/server-filesystem"]
			}
		}
	}`
	if err := os.WriteFile(path, []byte(data), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	result := scanClaudeDesktop(path, map[string]bool{})
	if len(result) != 1 {
		t.Fatalf("expected 1 server, got %d", len(result))
	}
	if result[0].Source != "claude-desktop" {
		t.Fatalf("expected source claude-desktop, got %q", result[0].Source)
	}
}

func TestScanForServers_Integration(t *testing.T) {
	// Create a temp home with both config files
	fakeHome := t.TempDir()

	origHomeDir := homeDir
	t.Cleanup(func() { homeDir = origHomeDir })
	homeDir = func() (string, error) { return fakeHome, nil }

	// Create Claude Code settings
	claudeDir := filepath.Join(fakeHome, ".claude")
	os.MkdirAll(claudeDir, 0755)
	ccData := `{
		"mcpServers": {
			"code-server": {"command": "node", "args": ["cc-server.js"]}
		}
	}`
	os.WriteFile(filepath.Join(claudeDir, "settings.json"), []byte(ccData), 0644)

	// Create Claude Desktop config (macOS path)
	desktopDir := filepath.Join(fakeHome, "Library", "Application Support", "Claude")
	os.MkdirAll(desktopDir, 0755)
	cdData := `{
		"mcpServers": {
			"desktop-server": {"command": "python", "args": ["desktop.py"]}
		}
	}`
	os.WriteFile(filepath.Join(desktopDir, "claude_desktop_config.json"), []byte(cdData), 0644)

	result := scanForServers(map[string]bool{})

	// Should find servers from both sources (on macOS at least)
	if len(result) < 1 {
		t.Fatalf("expected at least 1 discovered server, got %d", len(result))
	}

	foundCodes := 0
	for _, s := range result {
		if s.Source == "claude-code" {
			foundCodes++
		}
	}
	if foundCodes != 1 {
		t.Fatalf("expected 1 claude-code server, got %d", foundCodes)
	}
}
