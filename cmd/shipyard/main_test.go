package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestHelperProcessMain(t *testing.T) {
	if os.Getenv("SHIPYARD_HELPER_PROCESS") != "1" {
		return
	}

	args := os.Args
	for i, arg := range args {
		if arg == "--" {
			os.Args = append([]string{"shipyard"}, args[i+1:]...)
			break
		}
	}

	main()
	os.Exit(0)
}

func runShipyardMain(t *testing.T, args ...string) (int, string) {
	t.Helper()
	return runShipyardMainInDir(t, "", args...)
}

func runShipyardMainInDir(t *testing.T, dir string, args ...string) (int, string) {
	t.Helper()

	cmdArgs := append([]string{"-test.run=TestHelperProcessMain", "--"}, args...)
	cmd := exec.Command(os.Args[0], cmdArgs...)
	cmd.Env = append(os.Environ(), "SHIPYARD_HELPER_PROCESS=1")
	if dir != "" {
		cmd.Dir = dir
	}

	var output bytes.Buffer
	cmd.Stdout = &output
	cmd.Stderr = &output

	err := cmd.Run()
	if err == nil {
		return 0, output.String()
	}

	exitErr, ok := err.(*exec.ExitError)
	if !ok {
		t.Fatalf("run shipyard main: %v", err)
	}
	return exitErr.ExitCode(), output.String()
}

func TestMain_NoArgs(t *testing.T) {
	code, output := runShipyardMain(t)
	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if !strings.Contains(output, "usage: shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]") {
		t.Fatalf("expected usage output, got %q", output)
	}
}

func TestMain_UnknownCommand(t *testing.T) {
	code, output := runShipyardMain(t, "bogus")
	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if !strings.Contains(output, "unknown command: bogus") {
		t.Fatalf("expected unknown command error, got %q", output)
	}
}

func TestMain_WrapWithoutChildCommand(t *testing.T) {
	code, output := runShipyardMain(t, "wrap")
	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if !strings.Contains(output, "no child command specified") {
		t.Fatalf("expected missing child command error, got %q", output)
	}
}

func TestMain_ConfigWithNoServers(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "empty.json")
	if err := os.WriteFile(path, []byte(`{"servers":{}}`), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}

	code, output := runShipyardMain(t, "--config", path)
	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if !strings.Contains(output, "config does not define any servers") {
		t.Fatalf("expected empty servers error, got %q", output)
	}
}

func TestMain_ConfigMissingCommand(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "missing-command.json")
	if err := os.WriteFile(path, []byte(`{"servers":{"alpha":{}}}`), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}

	code, output := runShipyardMain(t, "--config", path)
	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if !strings.Contains(output, "config server is missing command") {
		t.Fatalf("expected missing command error, got %q", output)
	}
}

func TestRunWrap_ParsesFlagsAndSeparator(t *testing.T) {
	dir := t.TempDir()
	code, output := runShipyardMainInDir(t, dir, "--headless", "wrap", "--name", "alpha", "--port", "0", "--", "sh", "-c", "exit 0")
	if code != 0 {
		t.Fatalf("expected exit code 0, got %d; output=%q", code, output)
	}
	if strings.Contains(output, "error: no child command specified") {
		t.Fatalf("unexpected child command error, got %q", output)
	}
}

func TestRunWrap_ParsesCommandWithoutSeparator(t *testing.T) {
	dir := t.TempDir()
	code, output := runShipyardMainInDir(t, dir, "--headless", "wrap", "--name", "beta", "--port", "0", "sh", "-c", "exit 0")
	if code != 0 {
		t.Fatalf("expected exit code 0, got %d; output=%q", code, output)
	}
	if strings.Contains(output, "error: no child command specified") {
		t.Fatalf("unexpected child command error, got %q", output)
	}
}
