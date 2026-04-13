package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
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

func TestConfigUnmarshal_InvalidTopLevelBytes(t *testing.T) {
	var cfg Config
	if err := cfg.UnmarshalJSON([]byte(`not json at all`)); err == nil {
		t.Fatal("expected direct UnmarshalJSON error")
	}
}

func TestConfigUnmarshal_NoServersField(t *testing.T) {
	var cfg Config
	if err := json.Unmarshal([]byte(`{"web":{"port":9000}}`), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if cfg.Web.Port != 9000 {
		t.Fatalf("expected port 9000, got %d", cfg.Web.Port)
	}
	if cfg.Servers != nil {
		t.Fatalf("expected nil servers when field is absent, got %v", cfg.Servers)
	}
	if len(cfg.ServerOrder) != 0 {
		t.Fatalf("expected empty server order, got %v", cfg.ServerOrder)
	}
}

func TestConfigUnmarshal_ServersMustBeJSONObject(t *testing.T) {
	data := `{
		"servers": []
	}`

	var cfg Config
	err := json.Unmarshal([]byte(data), &cfg)
	if err == nil {
		t.Fatal("expected error for non-object servers field")
	}
	if got := err.Error(); !strings.Contains(got, "parse servers:") {
		t.Fatalf("expected parse servers error, got %q", got)
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

func TestConfigUnmarshal_ParseServerOrderErrors(t *testing.T) {
	orig := parseServerOrder
	t.Cleanup(func() { parseServerOrder = orig })

	tests := []struct {
		name string
		err  error
		want string
	}{
		{"read servers object", errors.New("bad open"), "bad open"},
		{"servers must be object", errors.New("servers must be a JSON object"), "servers must be a JSON object"},
		{"read server name", errors.New("read server name: bad key"), "read server name: bad key"},
		{"server name must be string", errors.New("server name must be a string"), "server name must be a string"},
		{"read server value", errors.New(`read server "alpha": bad value`), `read server "alpha": bad value`},
		{"close servers object", errors.New("close servers object: bad close"), "close servers object: bad close"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			parseServerOrder = func(raw json.RawMessage, appendName func(string), consumeValue func(*json.Decoder, string) error) error {
				return tc.err
			}

			var cfg Config
			err := json.Unmarshal([]byte(`{"servers":{"alpha":{"command":"x"}}}`), &cfg)
			if err == nil {
				t.Fatal("expected unmarshal error")
			}
			if got := err.Error(); !strings.Contains(got, tc.want) {
				t.Fatalf("expected %q in %q", tc.want, got)
			}
		})
	}
}

func TestConfigUnmarshal_ReadServerValueError(t *testing.T) {
	orig := parseServerOrder
	t.Cleanup(func() { parseServerOrder = orig })

	parseServerOrder = func(raw json.RawMessage, appendName func(string), consumeValue func(*json.Decoder, string) error) error {
		appendName("alpha")
		return consumeValue(json.NewDecoder(strings.NewReader("")), "alpha")
	}

	var cfg Config
	err := json.Unmarshal([]byte(`{"servers":{"alpha":{"command":"x"}}}`), &cfg)
	if err == nil {
		t.Fatal("expected decode error")
	}
	if !strings.Contains(err.Error(), `read server "alpha": EOF`) {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestLoadConfig_ReadErrorForDirectory(t *testing.T) {
	dir := t.TempDir()

	_, err := loadConfig(dir)
	if err == nil {
		t.Fatal("expected error when reading a directory as a config file")
	}
	if got := err.Error(); !strings.Contains(got, "read config file") {
		t.Fatalf("expected read config file error, got %q", got)
	}
}

// AC-20: Config supports bootstrap_token via env var expansion.
func TestConfigUnmarshal_AuthBlock_EnvVarExpansion(t *testing.T) {
	t.Setenv("MCP_RELAY_BOOTSTRAP_TOKEN", "secret-from-env")

	data := `{
		"servers": {"s": {"command": "echo"}},
		"auth": {
			"enabled": true,
			"bootstrap_token": "${MCP_RELAY_BOOTSTRAP_TOKEN}"
		}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if !cfg.Auth.Enabled {
		t.Error("expected auth.enabled to be true")
	}
	if cfg.Auth.BootstrapToken != "secret-from-env" {
		t.Errorf("expected bootstrap token 'secret-from-env', got %q", cfg.Auth.BootstrapToken)
	}
}

func TestConfigUnmarshal_AuthBlock_Disabled(t *testing.T) {
	data := `{
		"servers": {"s": {"command": "echo"}},
		"auth": {"enabled": false}
	}`

	var cfg Config
	if err := json.Unmarshal([]byte(data), &cfg); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if cfg.Auth.Enabled {
		t.Error("expected auth.enabled to be false")
	}
}

func TestExpandEnvVars(t *testing.T) {
	t.Setenv("TEST_VAR_A", "hello")
	t.Setenv("TEST_VAR_B", "world")

	got := expandEnvVars("${TEST_VAR_A}-${TEST_VAR_B}")
	want := "hello-world"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestExpandEnvVars_MissingVar(t *testing.T) {
	// A missing env var expands to "" (standard shell behaviour)
	got := expandEnvVars("prefix-${DEFINITELY_UNSET_VAR_XYZ}")
	if got != "prefix-" {
		t.Errorf("got %q, want %q", got, "prefix-")
	}
}

func TestExpandEnvVars_NoExpansion(t *testing.T) {
	got := expandEnvVars("no-vars-here")
	if got != "no-vars-here" {
		t.Errorf("got %q, want %q", got, "no-vars-here")
	}
}
