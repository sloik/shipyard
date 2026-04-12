package gateway

import (
	"path/filepath"
	"testing"
)

func TestStore_DefaultsEnabled(t *testing.T) {
	store, err := NewStore(filepath.Join(t.TempDir(), "gateway-policy.json"))
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	if !store.ServerEnabled("lmstudio") {
		t.Fatal("expected unknown server to default enabled")
	}
	if !store.ToolEnabled("lmstudio", "lms_status") {
		t.Fatal("expected unknown tool to default enabled")
	}
	if !store.EffectiveEnabled("lmstudio", "lms_status") {
		t.Fatal("expected unknown effective state to default enabled")
	}
}

func TestStore_PersistsServerAndToolPolicy(t *testing.T) {
	path := filepath.Join(t.TempDir(), "gateway-policy.json")
	store, err := NewStore(path)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	if err := store.SetServerEnabled("lmstudio", false); err != nil {
		t.Fatalf("SetServerEnabled: %v", err)
	}
	if err := store.SetToolEnabled("lmstudio", "lms_chat", false); err != nil {
		t.Fatalf("SetToolEnabled: %v", err)
	}

	reloaded, err := NewStore(path)
	if err != nil {
		t.Fatalf("reload NewStore: %v", err)
	}

	if reloaded.ServerEnabled("lmstudio") {
		t.Fatal("expected persisted server policy to remain disabled")
	}
	if reloaded.ToolEnabled("lmstudio", "lms_chat") {
		t.Fatal("expected persisted tool policy to remain disabled")
	}
	if reloaded.EffectiveEnabled("lmstudio", "lms_status") {
		t.Fatal("expected disabled server to disable sibling tools effectively")
	}
}
