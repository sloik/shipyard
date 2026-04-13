package auth

import (
	"path/filepath"
	"testing"
)

func newTestStore(t *testing.T) *Store {
	t.Helper()
	dir := t.TempDir()
	s, err := NewStore(filepath.Join(dir, "auth.db"), "bootstrap-secret")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func TestStore_GenerateAndAuthenticate(t *testing.T) {
	s := newTestStore(t)

	plaintext, id, err := s.GenerateToken("test-token", 60, []string{"fs:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}
	if id == 0 {
		t.Fatal("expected non-zero ID")
	}
	if len(plaintext) < 5 {
		t.Fatalf("plaintext too short: %q", plaintext)
	}
	if plaintext[:3] != "rl_" {
		t.Fatalf("expected rl_ prefix, got %q", plaintext[:3])
	}

	rec, err := s.Authenticate(plaintext)
	if err != nil {
		t.Fatalf("Authenticate: %v", err)
	}
	if rec.ID != id {
		t.Errorf("ID mismatch: got %d, want %d", rec.ID, id)
	}
	if rec.Name != "test-token" {
		t.Errorf("name mismatch: got %q", rec.Name)
	}
	if rec.RateLimitPerMin != 60 {
		t.Errorf("rate limit mismatch: got %d", rec.RateLimitPerMin)
	}
	if len(rec.Scopes) != 1 || rec.Scopes[0] != "fs:*" {
		t.Errorf("scopes mismatch: got %v", rec.Scopes)
	}
}

// AC-16: tokens stored as SHA-256 hashes — plaintext must not be in DB.
func TestStore_PlaintextNotStoredInDB(t *testing.T) {
	s := newTestStore(t)

	plaintext, _, err := s.GenerateToken("secret", 0, nil)
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	// Query the raw hash column — it must not equal the plaintext
	var hash string
	err = s.db.QueryRow("SELECT hash FROM tokens WHERE name='secret'").Scan(&hash)
	if err != nil {
		t.Fatalf("query hash: %v", err)
	}

	if hash == plaintext {
		t.Error("plaintext stored in hash column")
	}
	if len(hash) != 64 {
		t.Errorf("hash should be 64 hex chars, got %d", len(hash))
	}
}

func TestStore_AuthenticateInvalidToken(t *testing.T) {
	s := newTestStore(t)

	_, err := s.Authenticate("rl_notarealtoken00000000000000000")
	if err == nil {
		t.Fatal("expected error for unknown token")
	}
}

func TestStore_DeleteToken(t *testing.T) {
	s := newTestStore(t)

	plaintext, id, err := s.GenerateToken("to-delete", 0, nil)
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	// Token authenticates before deletion
	if _, err := s.Authenticate(plaintext); err != nil {
		t.Fatalf("Authenticate before delete: %v", err)
	}

	if err := s.DeleteToken(id); err != nil {
		t.Fatalf("DeleteToken: %v", err)
	}

	// Token must not authenticate after deletion (AC-12)
	_, err = s.Authenticate(plaintext)
	if err == nil {
		t.Fatal("expected auth failure after deletion")
	}
}

func TestStore_DeleteToken_NotFound(t *testing.T) {
	s := newTestStore(t)

	err := s.DeleteToken(9999)
	if err == nil {
		t.Fatal("expected error for non-existent token")
	}
}

func TestStore_UpdateScopes(t *testing.T) {
	s := newTestStore(t)

	plaintext, id, err := s.GenerateToken("scoped", 0, []string{"old:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	// Verify original scopes
	rec, _ := s.Authenticate(plaintext)
	if len(rec.Scopes) != 1 || rec.Scopes[0] != "old:*" {
		t.Fatalf("unexpected initial scopes: %v", rec.Scopes)
	}

	// Update scopes (AC-18)
	if err := s.UpdateScopes(id, []string{"new:read", "new:write"}); err != nil {
		t.Fatalf("UpdateScopes: %v", err)
	}

	rec, _ = s.Authenticate(plaintext)
	if len(rec.Scopes) != 2 {
		t.Fatalf("expected 2 scopes after update, got %v", rec.Scopes)
	}
}

func TestStore_ListTokens(t *testing.T) {
	s := newTestStore(t)

	_, _, err := s.GenerateToken("alpha", 0, nil)
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}
	_, _, err = s.GenerateToken("beta", 0, []string{"s:t"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	tokens, err := s.ListTokens()
	if err != nil {
		t.Fatalf("ListTokens: %v", err)
	}
	if len(tokens) != 2 {
		t.Fatalf("expected 2 tokens, got %d", len(tokens))
	}
}

// AC-9, AC-10: bootstrap token works initially; invalidated after first admin token created.
func TestStore_BootstrapToken(t *testing.T) {
	s := newTestStore(t) // bootstrap = "bootstrap-secret"

	if !s.AuthenticateBootstrap("bootstrap-secret") {
		t.Fatal("bootstrap token should work initially")
	}

	// Create first admin token — this should invalidate bootstrap
	_, _, err := s.GenerateToken("admin", 0, []string{"*:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	// Bootstrap should now be rejected (AC-10)
	if s.AuthenticateBootstrap("bootstrap-secret") {
		t.Fatal("bootstrap token should be invalidated after first admin token")
	}
}

func TestStore_BootstrapToken_WrongValue(t *testing.T) {
	s := newTestStore(t)

	if s.AuthenticateBootstrap("wrong-secret") {
		t.Fatal("wrong bootstrap token should not authenticate")
	}
}

func TestStore_GetStats(t *testing.T) {
	s := newTestStore(t)

	plaintext, id, err := s.GenerateToken("stats-test", 0, nil)
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	// Before any use, last_used_at is nil
	stats, err := s.GetStats(id)
	if err != nil {
		t.Fatalf("GetStats before use: %v", err)
	}
	if stats.LastUsedAt != nil {
		t.Error("expected nil last_used_at before any auth")
	}

	// Authenticate to set last_used_at
	if _, err := s.Authenticate(plaintext); err != nil {
		t.Fatalf("Authenticate: %v", err)
	}

	stats, err = s.GetStats(id)
	if err != nil {
		t.Fatalf("GetStats after use: %v", err)
	}
	if stats.LastUsedAt == nil {
		t.Error("expected non-nil last_used_at after auth (AC-19)")
	}
}

func TestStore_BootstrapUsed_PersistsAcrossReopen(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "auth.db")

	// Open store and create first admin token
	s1, err := NewStore(dbPath, "bootstrap-secret")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	_, _, err = s1.GenerateToken("admin", 0, nil)
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}
	if s1.AuthenticateBootstrap("bootstrap-secret") {
		t.Fatal("bootstrap should be invalid in s1")
	}
	s1.Close()

	// Reopen — bootstrap_used flag must still be set
	s2, err := NewStore(dbPath, "bootstrap-secret")
	if err != nil {
		t.Fatalf("NewStore reopen: %v", err)
	}
	defer s2.Close()
	if s2.AuthenticateBootstrap("bootstrap-secret") {
		t.Fatal("bootstrap should still be invalid after reopen")
	}
}
