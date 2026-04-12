package gateway

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

type Store struct {
	path string

	mu   sync.RWMutex
	data persistedPolicy
}

type persistedPolicy struct {
	Servers map[string]bool            `json:"servers"`
	Tools   map[string]map[string]bool `json:"tools"`
}

func NewStore(path string) (*Store, error) {
	s := &Store{
		path: path,
		data: persistedPolicy{
			Servers: map[string]bool{},
			Tools:   map[string]map[string]bool{},
		},
	}

	if err := s.load(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Store) ServerEnabled(server string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()

	enabled, ok := s.data.Servers[server]
	if !ok {
		return true
	}
	return enabled
}

func (s *Store) ToolEnabled(server, tool string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()

	tools, ok := s.data.Tools[server]
	if !ok {
		return true
	}
	enabled, ok := tools[tool]
	if !ok {
		return true
	}
	return enabled
}

func (s *Store) EffectiveEnabled(server, tool string) bool {
	return s.ServerEnabled(server) && s.ToolEnabled(server, tool)
}

func (s *Store) SetServerEnabled(server string, enabled bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.data.Servers[server] = enabled
	return s.saveLocked()
}

func (s *Store) SetToolEnabled(server, tool string, enabled bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.data.Tools[server] == nil {
		s.data.Tools[server] = map[string]bool{}
	}
	s.data.Tools[server][tool] = enabled
	return s.saveLocked()
}

func (s *Store) Snapshot() map[string]interface{} {
	s.mu.RLock()
	defer s.mu.RUnlock()

	servers := make(map[string]bool, len(s.data.Servers))
	for name, enabled := range s.data.Servers {
		servers[name] = enabled
	}

	tools := make(map[string]map[string]bool, len(s.data.Tools))
	for server, items := range s.data.Tools {
		copied := make(map[string]bool, len(items))
		for name, enabled := range items {
			copied[name] = enabled
		}
		tools[server] = copied
	}

	return map[string]interface{}{
		"servers": servers,
		"tools":   tools,
	}
}

func (s *Store) load() error {
	data, err := os.ReadFile(s.path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("read gateway policy %s: %w", s.path, err)
	}

	var loaded persistedPolicy
	if err := json.Unmarshal(data, &loaded); err != nil {
		return fmt.Errorf("parse gateway policy %s: %w", s.path, err)
	}
	if loaded.Servers == nil {
		loaded.Servers = map[string]bool{}
	}
	if loaded.Tools == nil {
		loaded.Tools = map[string]map[string]bool{}
	}

	s.mu.Lock()
	s.data = loaded
	s.mu.Unlock()
	return nil
}

func (s *Store) saveLocked() error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o755); err != nil {
		return fmt.Errorf("mkdir policy dir: %w", err)
	}

	body, err := json.MarshalIndent(s.data, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal gateway policy: %w", err)
	}

	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, body, 0o644); err != nil {
		return fmt.Errorf("write gateway policy temp file: %w", err)
	}
	if err := os.Rename(tmp, s.path); err != nil {
		return fmt.Errorf("persist gateway policy: %w", err)
	}
	return nil
}
