package web

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// homeDir returns the user's home directory. Overridable for testing.
var homeDir = os.UserHomeDir

// scanForServers reads known MCP client config files and returns discovered servers.
func scanForServers(existing map[string]bool) []DiscoveredServer {
	var discovered []DiscoveredServer

	home, err := homeDir()
	if err != nil {
		return discovered
	}

	// Claude Code: ~/.claude/settings.json
	claudeCodePath := filepath.Join(home, ".claude", "settings.json")
	discovered = append(discovered, scanClaudeCode(claudeCodePath, existing)...)

	// Claude Desktop: platform-specific path
	var claudeDesktopPath string
	switch runtime.GOOS {
	case "darwin":
		claudeDesktopPath = filepath.Join(home, "Library", "Application Support", "Claude", "claude_desktop_config.json")
	case "linux":
		claudeDesktopPath = filepath.Join(home, ".config", "Claude", "claude_desktop_config.json")
	case "windows":
		appData := os.Getenv("APPDATA")
		if appData != "" {
			claudeDesktopPath = filepath.Join(appData, "Claude", "claude_desktop_config.json")
		}
	}
	if claudeDesktopPath != "" {
		discovered = append(discovered, scanClaudeDesktop(claudeDesktopPath, existing)...)
	}

	return discovered
}

// scanClaudeCode reads Claude Code settings.json for mcpServers.
func scanClaudeCode(path string, existing map[string]bool) []DiscoveredServer {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}

	var settings struct {
		MCPServers map[string]struct {
			Command string            `json:"command"`
			Args    []string          `json:"args"`
			Env     map[string]string `json:"env"`
			Cwd     string            `json:"cwd"`
		} `json:"mcpServers"`
	}
	if err := json.Unmarshal(data, &settings); err != nil {
		return nil
	}

	var result []DiscoveredServer
	for name, srv := range settings.MCPServers {
		if srv.Command == "" {
			continue
		}
		status := "new"
		if existing[name] {
			status = "already_imported"
		} else {
			// Check for duplicates by command
			for _, d := range result {
				if d.Command == srv.Command && strings.Join(d.Args, " ") == strings.Join(srv.Args, " ") {
					status = "duplicate"
					break
				}
			}
		}
		result = append(result, DiscoveredServer{
			Name:    name,
			Command: srv.Command,
			Args:    srv.Args,
			Env:     srv.Env,
			Source:  "claude-code",
			Status:  status,
		})
	}
	return result
}

// scanClaudeDesktop reads Claude Desktop config for mcpServers.
func scanClaudeDesktop(path string, existing map[string]bool) []DiscoveredServer {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}

	var config struct {
		MCPServers map[string]struct {
			Command string            `json:"command"`
			Args    []string          `json:"args"`
			Env     map[string]string `json:"env"`
			Cwd     string            `json:"cwd"`
		} `json:"mcpServers"`
	}
	if err := json.Unmarshal(data, &config); err != nil {
		return nil
	}

	var result []DiscoveredServer
	for name, srv := range config.MCPServers {
		if srv.Command == "" {
			continue
		}
		status := "new"
		if existing[name] {
			status = "already_imported"
		}
		result = append(result, DiscoveredServer{
			Name:    name,
			Command: srv.Command,
			Args:    srv.Args,
			Env:     srv.Env,
			Source:  "claude-desktop",
			Status:  status,
		})
	}
	return result
}
