// Package auth implements bearer token authentication for the Shipyard MCP proxy.
// Tokens are stored as SHA-256 hashes in SQLite; plaintext is shown only once at creation.
package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"sync"
	"time"

	_ "github.com/ncruces/go-sqlite3/driver"
	_ "github.com/ncruces/go-sqlite3/embed"
)

// Store manages token persistence in SQLite.
type Store struct {
	db              *sql.DB
	mu              sync.Mutex
	bootstrapUsed   bool // set to true after first admin token is created
	bootstrapToken  string
}

// TokenRecord holds token metadata (never the plaintext or hash).
type TokenRecord struct {
	ID               int64      `json:"id"`
	Name             string     `json:"name"`
	CreatedAt        time.Time  `json:"created_at"`
	LastUsedAt       *time.Time `json:"last_used_at,omitempty"`
	RateLimitPerMin  int        `json:"rate_limit_per_minute,omitempty"`
	Scopes           []string   `json:"scopes"`
	Revoked          bool       `json:"revoked"`
}

// openAuthDB can be overridden in tests.
var openAuthDB = func(path string) (*sql.DB, error) {
	return sql.Open("sqlite3", path)
}

// NewStore opens (or creates) the auth SQLite database and initialises the schema.
func NewStore(dbPath, bootstrapToken string) (*Store, error) {
	db, err := openAuthDB(dbPath)
	if err != nil {
		return nil, fmt.Errorf("open auth db: %w", err)
	}

	_, _ = db.Exec("PRAGMA journal_mode=WAL")

	if _, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS tokens (
			id                 INTEGER PRIMARY KEY AUTOINCREMENT,
			name               TEXT NOT NULL,
			hash               TEXT NOT NULL UNIQUE,
			created_at         TEXT NOT NULL,
			last_used_at       TEXT,
			rate_limit_per_min INTEGER NOT NULL DEFAULT 0,
			is_revoked         INTEGER NOT NULL DEFAULT 0
		);
		CREATE TABLE IF NOT EXISTS token_scopes (
			id         INTEGER PRIMARY KEY AUTOINCREMENT,
			token_id   INTEGER NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
			pattern    TEXT NOT NULL
		);
		CREATE INDEX IF NOT EXISTS idx_token_scopes_token ON token_scopes(token_id);
		CREATE TABLE IF NOT EXISTS settings (
			key   TEXT PRIMARY KEY,
			value TEXT NOT NULL
		);
	`); err != nil {
		db.Close()
		return nil, fmt.Errorf("init auth schema: %w", err)
	}

	// Migrate existing DBs: add is_revoked if not present.
	if err := migrate(db); err != nil {
		db.Close()
		return nil, fmt.Errorf("migrate auth schema: %w", err)
	}

	s := &Store{
		db:             db,
		bootstrapToken: bootstrapToken,
	}

	// Check if bootstrap has already been used (persisted across restarts).
	var val string
	err = db.QueryRow("SELECT value FROM settings WHERE key='bootstrap_used'").Scan(&val)
	if err == nil && val == "1" {
		s.bootstrapUsed = true
	}

	return s, nil
}

// Close closes the underlying database.
func (s *Store) Close() error {
	return s.db.Close()
}

// GenerateToken creates a new token, stores its SHA-256 hash, and returns the plaintext.
// The plaintext is rl_<32 hex bytes>. It will never be retrievable again.
func (s *Store) GenerateToken(name string, rateLimitPerMin int, scopes []string) (plaintext string, id int64, err error) {
	// Generate 16 random bytes → 32 hex chars
	buf := make([]byte, 16)
	if _, err = rand.Read(buf); err != nil {
		return "", 0, fmt.Errorf("generate token bytes: %w", err)
	}
	plaintext = "rl_" + hex.EncodeToString(buf)
	hash := hashToken(plaintext)

	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now().UTC().Format(time.RFC3339Nano)

	tx, err := s.db.Begin()
	if err != nil {
		return "", 0, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	res, err := tx.Exec(
		"INSERT INTO tokens(name, hash, created_at, rate_limit_per_min) VALUES(?,?,?,?)",
		name, hash, now, rateLimitPerMin,
	)
	if err != nil {
		return "", 0, fmt.Errorf("insert token: %w", err)
	}
	id, err = res.LastInsertId()
	if err != nil {
		return "", 0, fmt.Errorf("last insert id: %w", err)
	}

	for _, scope := range scopes {
		if _, err = tx.Exec("INSERT INTO token_scopes(token_id, pattern) VALUES(?,?)", id, scope); err != nil {
			return "", 0, fmt.Errorf("insert scope: %w", err)
		}
	}

	if err = tx.Commit(); err != nil {
		return "", 0, fmt.Errorf("commit: %w", err)
	}

	// Mark bootstrap as used once first admin token is created.
	s.markBootstrapUsed()

	return plaintext, id, nil
}

// markBootstrapUsed persists the bootstrap_used flag. Caller must not hold s.mu.
func (s *Store) markBootstrapUsed() {
	if s.bootstrapUsed {
		return
	}
	s.bootstrapUsed = true
	_, _ = s.db.Exec("INSERT OR REPLACE INTO settings(key,value) VALUES('bootstrap_used','1')")
}

// Authenticate looks up the token by its SHA-256 hash.
// Returns the TokenRecord and scopes, or an error if not found.
// It also updates last_used_at.
func (s *Store) Authenticate(plaintext string) (*TokenRecord, error) {
	hash := hashToken(plaintext)

	s.mu.Lock()
	defer s.mu.Unlock()

	var rec TokenRecord
	var createdStr string
	var lastUsedStr sql.NullString
	var isRevoked int

	err := s.db.QueryRow(
		"SELECT id, name, created_at, last_used_at, rate_limit_per_min, is_revoked FROM tokens WHERE hash=?",
		hash,
	).Scan(&rec.ID, &rec.Name, &createdStr, &lastUsedStr, &rec.RateLimitPerMin, &isRevoked)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("token not found")
	}
	if err != nil {
		return nil, fmt.Errorf("query token: %w", err)
	}
	if isRevoked != 0 {
		return nil, fmt.Errorf("token revoked")
	}

	if t, err := time.Parse(time.RFC3339Nano, createdStr); err == nil {
		rec.CreatedAt = t
	}
	if lastUsedStr.Valid {
		if t, err := time.Parse(time.RFC3339Nano, lastUsedStr.String); err == nil {
			rec.LastUsedAt = &t
		}
	}

	// Load scopes
	rows, err := s.db.Query("SELECT pattern FROM token_scopes WHERE token_id=?", rec.ID)
	if err != nil {
		return nil, fmt.Errorf("query scopes: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var p string
		if err := rows.Scan(&p); err != nil {
			return nil, fmt.Errorf("scan scope: %w", err)
		}
		rec.Scopes = append(rec.Scopes, p)
	}

	// Update last_used_at
	now := time.Now().UTC().Format(time.RFC3339Nano)
	_, _ = s.db.Exec("UPDATE tokens SET last_used_at=? WHERE id=?", now, rec.ID)

	return &rec, nil
}

// AuthenticateBootstrap checks whether the provided plaintext matches the bootstrap token
// and that bootstrap hasn't been invalidated yet.
func (s *Store) AuthenticateBootstrap(plaintext string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.bootstrapUsed || s.bootstrapToken == "" {
		return false
	}
	return plaintext == s.bootstrapToken
}

// ListTokens returns metadata for all tokens, including revoked ones (no hashes or plaintext).
func (s *Store) ListTokens() ([]TokenRecord, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rows, err := s.db.Query(
		"SELECT id, name, created_at, last_used_at, rate_limit_per_min, is_revoked FROM tokens ORDER BY id",
	)
	if err != nil {
		return nil, fmt.Errorf("list tokens: %w", err)
	}
	defer rows.Close()

	var results []TokenRecord
	for rows.Next() {
		var rec TokenRecord
		var createdStr string
		var lastUsedStr sql.NullString
		var isRevoked int
		if err := rows.Scan(&rec.ID, &rec.Name, &createdStr, &lastUsedStr, &rec.RateLimitPerMin, &isRevoked); err != nil {
			return nil, fmt.Errorf("scan token: %w", err)
		}
		if t, err := time.Parse(time.RFC3339Nano, createdStr); err == nil {
			rec.CreatedAt = t
		}
		if lastUsedStr.Valid {
			if t, err := time.Parse(time.RFC3339Nano, lastUsedStr.String); err == nil {
				rec.LastUsedAt = &t
			}
		}
		rec.Revoked = isRevoked != 0
		results = append(results, rec)
	}

	// Load scopes for each token
	for i := range results {
		scopeRows, err := s.db.Query("SELECT pattern FROM token_scopes WHERE token_id=?", results[i].ID)
		if err != nil {
			return nil, fmt.Errorf("list scopes: %w", err)
		}
		for scopeRows.Next() {
			var p string
			if err := scopeRows.Scan(&p); err != nil {
				scopeRows.Close()
				return nil, fmt.Errorf("scan scope: %w", err)
			}
			results[i].Scopes = append(results[i].Scopes, p)
		}
		scopeRows.Close()
	}

	return results, nil
}

// GetToken returns metadata for a single token by ID.
func (s *Store) GetToken(id int64) (*TokenRecord, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	var rec TokenRecord
	var createdStr string
	var lastUsedStr sql.NullString
	var isRevoked int

	err := s.db.QueryRow(
		"SELECT id, name, created_at, last_used_at, rate_limit_per_min, is_revoked FROM tokens WHERE id=?", id,
	).Scan(&rec.ID, &rec.Name, &createdStr, &lastUsedStr, &rec.RateLimitPerMin, &isRevoked)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("token not found")
	}
	if err != nil {
		return nil, fmt.Errorf("get token: %w", err)
	}
	rec.Revoked = isRevoked != 0

	if t, err := time.Parse(time.RFC3339Nano, createdStr); err == nil {
		rec.CreatedAt = t
	}
	if lastUsedStr.Valid {
		if t, err := time.Parse(time.RFC3339Nano, lastUsedStr.String); err == nil {
			rec.LastUsedAt = &t
		}
	}

	rows, err := s.db.Query("SELECT pattern FROM token_scopes WHERE token_id=?", rec.ID)
	if err != nil {
		return nil, fmt.Errorf("query scopes: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var p string
		if err := rows.Scan(&p); err != nil {
			return nil, fmt.Errorf("scan scope: %w", err)
		}
		rec.Scopes = append(rec.Scopes, p)
	}

	return &rec, nil
}

// DeleteToken soft-deletes a token by setting is_revoked=1.
func (s *Store) DeleteToken(id int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	res, err := s.db.Exec("UPDATE tokens SET is_revoked=1 WHERE id=?", id)
	if err != nil {
		return fmt.Errorf("revoke token: %w", err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return fmt.Errorf("token not found")
	}
	return nil
}

// UpdateScopes replaces the scopes for a token.
func (s *Store) UpdateScopes(id int64, scopes []string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	tx, err := s.db.Begin()
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	// Verify the token exists
	var count int
	if err := tx.QueryRow("SELECT COUNT(*) FROM tokens WHERE id=?", id).Scan(&count); err != nil {
		return fmt.Errorf("check token: %w", err)
	}
	if count == 0 {
		return fmt.Errorf("token not found")
	}

	if _, err := tx.Exec("DELETE FROM token_scopes WHERE token_id=?", id); err != nil {
		return fmt.Errorf("delete scopes: %w", err)
	}
	for _, scope := range scopes {
		if _, err := tx.Exec("INSERT INTO token_scopes(token_id, pattern) VALUES(?,?)", id, scope); err != nil {
			return fmt.Errorf("insert scope: %w", err)
		}
	}

	return tx.Commit()
}

// TokenStats holds call count and last-used timestamp for a token.
type TokenStats struct {
	ID         int64      `json:"id"`
	LastUsedAt *time.Time `json:"last_used_at,omitempty"`
}

// GetStats returns stats for a token.
func (s *Store) GetStats(id int64) (*TokenStats, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	var stats TokenStats
	stats.ID = id

	var lastUsedStr sql.NullString
	err := s.db.QueryRow(
		"SELECT last_used_at FROM tokens WHERE id=?", id,
	).Scan(&lastUsedStr)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("token not found")
	}
	if err != nil {
		return nil, fmt.Errorf("get stats: %w", err)
	}

	if lastUsedStr.Valid {
		if t, err := time.Parse(time.RFC3339Nano, lastUsedStr.String); err == nil {
			stats.LastUsedAt = &t
		}
	}

	return &stats, nil
}

// migrate applies incremental schema changes to existing databases.
func migrate(db *sql.DB) error {
	if !columnExists(db, "tokens", "is_revoked") {
		if _, err := db.Exec(`ALTER TABLE tokens ADD COLUMN is_revoked INTEGER NOT NULL DEFAULT 0`); err != nil {
			return fmt.Errorf("add is_revoked column: %w", err)
		}
	}
	return nil
}

// columnExists checks whether a column exists in a SQLite table.
func columnExists(db *sql.DB, table, column string) bool {
	rows, err := db.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		return false
	}
	defer rows.Close()
	for rows.Next() {
		var cid int
		var name, typ string
		var notNull, pk int
		var dflt sql.NullString
		if err := rows.Scan(&cid, &name, &typ, &notNull, &dflt, &pk); err != nil {
			continue
		}
		if name == column {
			return true
		}
	}
	return false
}

// hashToken returns the hex-encoded SHA-256 hash of the token plaintext.
func hashToken(plaintext string) string {
	h := sha256.Sum256([]byte(plaintext))
	return hex.EncodeToString(h[:])
}
