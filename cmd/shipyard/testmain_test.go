package main

import (
	"os"
	"strings"
	"testing"
)

// realHome is the developer's actual home directory, captured before isolation.
var realHome string

// TestMain points the home directory at a throwaway directory so no test (nor
// any helper subprocess, which inherits the environment) can open the real
// Shipyard data directory (~/Library/Application Support/Shipyard), which
// holds a live capture database.
func TestMain(m *testing.M) {
	realHome, _ = os.UserHomeDir()
	if os.Getenv("SHIPYARD_TEST_REAL_HOME") == "" {
		os.Setenv("SHIPYARD_TEST_REAL_HOME", realHome) // inherited by helper subprocesses
	} else {
		realHome = os.Getenv("SHIPYARD_TEST_REAL_HOME")
	}
	dataDirGuard = func(dir string) {
		if realHome != "" && (dir == realHome || strings.HasPrefix(dir, realHome+string(os.PathSeparator))) {
			panic("test resolved the data dir under the real home (live install): " + dir)
		}
	}
	home, err := os.MkdirTemp("", "shipyard-test-home-")
	if err != nil {
		panic(err)
	}
	os.Setenv("HOME", home)
	os.Setenv("APPDATA", home)
	os.Setenv("USERPROFILE", home)
	code := m.Run()
	os.RemoveAll(home)
	os.Exit(code)
}

func TestDataDirIsIsolatedFromRealInstall(t *testing.T) {
	dir := dataDir()
	if realHome == "" {
		t.Fatal("real home not captured")
	}
	if strings.HasPrefix(dir, realHome+string(os.PathSeparator)) {
		t.Fatalf("dataDir %q is under the real home %q", dir, realHome)
	}
}
