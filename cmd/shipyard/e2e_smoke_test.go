package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
)

func repoRoot(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
}

func buildGoBinary(t *testing.T, root, pkg, name string) string {
	t.Helper()

	outDir := t.TempDir()
	outPath := filepath.Join(outDir, name)
	cmd := exec.Command("go", "build", "-o", outPath, pkg)
	cmd.Dir = root
	var stderr bytes.Buffer
	cmd.Stdout = io.Discard
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		t.Fatalf("go build %s: %v\n%s", pkg, err, stderr.String())
	}
	return outPath
}

func freePort(t *testing.T) int {
	t.Helper()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen on ephemeral port: %v", err)
	}
	defer ln.Close()

	return ln.Addr().(*net.TCPAddr).Port
}

func waitForHTTP(t *testing.T, url string, check func(*http.Response, []byte) bool) []byte {
	t.Helper()

	client := &http.Client{Timeout: 1 * time.Second}
	deadline := time.Now().Add(20 * time.Second)
	var lastErr error

	for time.Now().Before(deadline) {
		resp, err := client.Get(url)
		if err == nil {
			body, readErr := io.ReadAll(resp.Body)
			resp.Body.Close()
			if readErr == nil && check(resp, body) {
				return body
			}
			lastErr = fmt.Errorf("unexpected response %s: %s", resp.Status, strings.TrimSpace(string(body)))
		} else {
			lastErr = err
		}
		time.Sleep(50 * time.Millisecond)
	}

	t.Fatalf("timed out waiting for %s: %v", url, lastErr)
	return nil
}

func startShipyardProcess(t *testing.T, binary, workDir, configPath string) (*exec.Cmd, *bytes.Buffer) {
	t.Helper()

	cmd := exec.Command(binary, "--headless", "--config", configPath)
	cmd.Dir = workDir

	var output bytes.Buffer
	cmd.Stdout = &output
	cmd.Stderr = &output

	if err := cmd.Start(); err != nil {
		t.Fatalf("start shipyard: %v", err)
	}

	return cmd, &output
}

func TestShipyardE2E_ConfigMode_RealProcessFlow(t *testing.T) {
	root := repoRoot(t)
	shipyardBin := buildGoBinary(t, root, "./cmd/shipyard", "shipyard")
	childBin := buildGoBinary(t, root, "./internal/teststubchild", "stubchild")

	workDir := t.TempDir()
	port := freePort(t)
	config := fmt.Sprintf(`{
		"servers": {
			"alpha": {
				"command": %q,
				"args": [],
				"cwd": %q
			}
		},
		"web": {"port": %d}
	}`, childBin, workDir, port)
	configPath := filepath.Join(workDir, "config.json")
	if err := os.WriteFile(configPath, []byte(config), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}

	cmd, output := startShipyardProcess(t, shipyardBin, workDir, configPath)
	t.Cleanup(func() {
		if cmd.Process != nil && cmd.ProcessState == nil {
			_ = cmd.Process.Kill()
		}
	})

	baseURL := fmt.Sprintf("http://127.0.0.1:%d", port)
	waitForHTTP(t, baseURL+"/api/servers", func(resp *http.Response, body []byte) bool {
		if resp.StatusCode != http.StatusOK {
			return false
		}
		var servers []captureServerInfo
		if err := json.Unmarshal(body, &servers); err != nil {
			return false
		}
		return len(servers) == 1 && servers[0].Name == "alpha"
	})

	waitForHTTP(t, baseURL+"/api/tools?server=alpha", func(resp *http.Response, body []byte) bool {
		if resp.StatusCode != http.StatusOK {
			return false
		}
		var tools map[string]any
		if err := json.Unmarshal(body, &tools); err != nil {
			return false
		}
		items, ok := tools["tools"].([]any)
		return ok && len(items) == 1
	})

	callBody := `{"server":"alpha","tool":"echo","arguments":{"message":"hello"}}`
	resp, err := http.Post(baseURL+"/api/tools/call", "application/json", strings.NewReader(callBody))
	if err != nil {
		t.Fatalf("post tools/call: %v", err)
	}
	callBytes, err := io.ReadAll(resp.Body)
	resp.Body.Close()
	if err != nil {
		t.Fatalf("read tools/call body: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 from tools/call, got %d body=%s", resp.StatusCode, string(callBytes))
	}
	var callResp map[string]any
	if err := json.Unmarshal(callBytes, &callResp); err != nil {
		t.Fatalf("unmarshal tools/call response: %v", err)
	}
	if _, ok := callResp["latency_ms"]; !ok {
		t.Fatalf("expected latency_ms in tools/call response: %v", callResp)
	}
	result, ok := callResp["result"].(map[string]any)
	if !ok {
		t.Fatalf("expected result object in tools/call response: %v", callResp)
	}
	content, ok := result["content"].([]any)
	if !ok || len(content) != 1 {
		t.Fatalf("expected result content array, got %v", result)
	}

	waitForHTTP(t, baseURL+"/api/traffic?page=1&page_size=20&server=alpha&method=tools/call", func(resp *http.Response, body []byte) bool {
		if resp.StatusCode != http.StatusOK {
			return false
		}
		var page capture.TrafficPage
		if err := json.Unmarshal(body, &page); err != nil {
			return false
		}
		if page.TotalCount < 2 {
			return false
		}
		var sawReq, sawRes bool
		for _, item := range page.Items {
			if item.Method == "tools/call" && item.Direction == capture.DirectionClientToServer {
				sawReq = true
			}
			if item.Method == "tools/call" && item.Direction == capture.DirectionServerToClient {
				sawRes = true
			}
		}
		return sawReq && sawRes
	})

	if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatalf("signal shipyard: %v", err)
	}

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("shipyard exited with error: %v\n%s", err, output.String())
		}
	case <-time.After(10 * time.Second):
		t.Fatalf("timed out waiting for shipyard shutdown\n%s", output.String())
	}
}

type captureServerInfo struct {
	Name   string `json:"name"`
	Status string `json:"status"`
}
