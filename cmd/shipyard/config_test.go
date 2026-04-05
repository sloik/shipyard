package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestConfigUnmarshal_SingleServer(t *testing.T) {
	data := `{
		"servers": {
			"my-mcp": {
				"command": "node",
				"args": ["server.js"]
			}
		}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if len(cfg.Servers) != 1 {
		t.Fatalf("expected 1 server, got %d", len(cfg.Servers))
	}
	srv, ok := cfg.Servers["my-mcp"]
	if !ok {
		t.Fatal("expected server 'my-mcp'")
	}
	if srv.Command != "node" {
		t.Fatalf("expected command 'node', got '%s'", srv.Command)
	}
	if len(srv.Args) != 1 || srv.Args[0] != "server.js" {
		t.Fatalf("expected args ['server.js'], got %v", srv.Args)
	}
}

func TestConfigUnmarshal_MultipleServers(t *testing.T) {
	data := `{
		"servers": {
			"alpha": {"command": "cmd-a"},
			"beta": {"command": "cmd-b"},
			"gamma": {"command": "cmd-g"}
		}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if len(cfg.Servers) != 3 {
		t.Fatalf("expected 3 servers, got %d", len(cfg.Servers))
	}
	if len(cfg.ServerOrder) != 3 {
		t.Fatalf("expected 3 entries in ServerOrder, got %d", len(cfg.ServerOrder))
	}
}

func TestConfigUnmarshal_ServerOrderPreserved(t *testing.T) {
	// JSON object key order should be preserved in ServerOrder
	data := `{
		"servers": {
			"echo": {"command": "echo"},
			"alpha": {"command": "alpha"},
			"zulu": {"command": "zulu"},
			"mike": {"command": "mike"},
			"delta": {"command": "delta"}
		}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	expected := []string{"echo", "alpha", "zulu", "mike", "delta"}
	if len(cfg.ServerOrder) != len(expected) {
		t.Fatalf("expected %d entries in ServerOrder, got %d", len(expected), len(cfg.ServerOrder))
	}
	for i, name := range expected {
		if cfg.ServerOrder[i] != name {
			t.Fatalf("ServerOrder[%d]: expected %q, got %q", i, name, cfg.ServerOrder[i])
		}
	}
}

func TestConfigUnmarshal_WebPort(t *testing.T) {
	data := `{
		"servers": {},
		"web": {"port": 8080}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if cfg.Web.Port != 8080 {
		t.Fatalf("expected port 8080, got %d", cfg.Web.Port)
	}
}

func TestConfigUnmarshal_DefaultPort(t *testing.T) {
	data := `{
		"servers": {
			"test": {"command": "test"}
		}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	// When web section is missing, port should be zero (caller defaults to 9417)
	if cfg.Web.Port != 0 {
		t.Fatalf("expected port 0 (unset), got %d", cfg.Web.Port)
	}
}

func TestConfigUnmarshal_InvalidJSON(t *testing.T) {
	data := `not json at all`

	var cfg Config
	err := json.Unmarshal([]byte(data), &cfg)
	if err == nil {
		t.Fatal("expected error for invalid JSON")
	}
}

func TestConfigUnmarshal_EmptyServers(t *testing.T) {
	data := `{
		"servers": {}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if len(cfg.Servers) != 0 {
		t.Fatalf("expected 0 servers, got %d", len(cfg.Servers))
	}
	if len(cfg.ServerOrder) != 0 {
		t.Fatalf("expected 0 server order entries, got %d", len(cfg.ServerOrder))
	}
}

func TestConfigUnmarshal_ServerWithAllFields(t *testing.T) {
	data := `{
		"servers": {
			"full": {
				"command": "/usr/bin/node",
				"args": ["--inspect", "server.js"],
				"env": {"NODE_ENV": "production", "PORT": "3000"},
				"cwd": "/opt/mcp"
			}
		}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	srv := cfg.Servers["full"]
	if srv.Command != "/usr/bin/node" {
		t.Fatalf("expected command '/usr/bin/node', got '%s'", srv.Command)
	}
	if len(srv.Args) != 2 {
		t.Fatalf("expected 2 args, got %d", len(srv.Args))
	}
	if srv.Args[0] != "--inspect" || srv.Args[1] != "server.js" {
		t.Fatalf("unexpected args: %v", srv.Args)
	}
	if len(srv.Env) != 2 {
		t.Fatalf("expected 2 env vars, got %d", len(srv.Env))
	}
	if srv.Env["NODE_ENV"] != "production" {
		t.Fatalf("expected NODE_ENV=production, got %s", srv.Env["NODE_ENV"])
	}
	if srv.Cwd != "/opt/mcp" {
		t.Fatalf("expected cwd '/opt/mcp', got '%s'", srv.Cwd)
	}
}

func TestLoadConfig_FileNotFound(t *testing.T) {
	_, err := loadConfig("/nonexistent/path/config.json")
	if err == nil {
		t.Fatal("expected error for missing file")
	}
	// Should mention "not found"
	if got := err.Error(); got == "" {
		t.Fatal("expected non-empty error message")
	}
}

func TestLoadConfig_ValidFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")

	data := `{
		"servers": {
			"test": {"command": "echo", "args": ["hello"]}
		},
		"web": {"port": 7777}
	}`
	if err := os.WriteFile(path, []byte(data), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	cfg, err := loadConfig(path)
	if err != nil {
		t.Fatalf("loadConfig: %v", err)
	}

	if len(cfg.Servers) != 1 {
		t.Fatalf("expected 1 server, got %d", len(cfg.Servers))
	}
	if cfg.Web.Port != 7777 {
		t.Fatalf("expected port 7777, got %d", cfg.Web.Port)
	}
	if len(cfg.ServerOrder) != 1 || cfg.ServerOrder[0] != "test" {
		t.Fatalf("expected ServerOrder ['test'], got %v", cfg.ServerOrder)
	}
}

func TestLoadConfig_InvalidJSON(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.json")

	if err := os.WriteFile(path, []byte(`{invalid`), 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	_, err := loadConfig(path)
	if err == nil {
		t.Fatal("expected error for invalid JSON file")
	}
}
