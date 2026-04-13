package auth

import "testing"

func TestMatchScope(t *testing.T) {
	tests := []struct {
		name    string
		scopes  []string
		server  string
		tool    string
		want    bool
	}{
		// AC-3: filesystem:* allows filesystem:read_file but not cortex:cortex_search
		{
			name:   "exact server wildcard tool match",
			scopes: []string{"filesystem:*"},
			server: "filesystem",
			tool:   "read_file",
			want:   true,
		},
		{
			name:   "exact server wildcard tool no cross-server match",
			scopes: []string{"filesystem:*"},
			server: "cortex",
			tool:   "cortex_search",
			want:   false,
		},
		// AC-4: *:* allows anything
		{
			name:   "star:star allows any tool",
			scopes: []string{"*:*"},
			server: "cortex",
			tool:   "cortex_search",
			want:   true,
		},
		{
			name:   "star:star allows any server",
			scopes: []string{"*:*"},
			server: "filesystem",
			tool:   "write_file",
			want:   true,
		},
		// AC-17: cortex:cortex_* matches cortex:cortex_search and cortex:cortex_add but not cortex:list_tools
		{
			name:   "prefix wildcard matches cortex_search",
			scopes: []string{"cortex:cortex_*"},
			server: "cortex",
			tool:   "cortex_search",
			want:   true,
		},
		{
			name:   "prefix wildcard matches cortex_add",
			scopes: []string{"cortex:cortex_*"},
			server: "cortex",
			tool:   "cortex_add",
			want:   true,
		},
		{
			name:   "prefix wildcard does NOT match list_tools",
			scopes: []string{"cortex:cortex_*"},
			server: "cortex",
			tool:   "list_tools",
			want:   false,
		},
		// Multiple scopes — any match is sufficient
		{
			name:   "multi-scope first matches",
			scopes: []string{"fs:read", "fs:write"},
			server: "fs",
			tool:   "read",
			want:   true,
		},
		{
			name:   "multi-scope second matches",
			scopes: []string{"fs:read", "fs:write"},
			server: "fs",
			tool:   "write",
			want:   true,
		},
		{
			name:   "multi-scope none matches",
			scopes: []string{"fs:read", "fs:write"},
			server: "fs",
			tool:   "delete",
			want:   false,
		},
		// Empty scopes — R5/R6 spec says scope list empty means "no access" but that's
		// handled at the calling layer (empty scopes → MatchScope not called).
		// Here we just verify behaviour: no patterns → no match.
		{
			name:   "empty scopes",
			scopes: []string{},
			server: "any",
			tool:   "any",
			want:   false,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := MatchScope(tc.scopes, tc.server, tc.tool)
			if got != tc.want {
				t.Errorf("MatchScope(%v, %q, %q) = %v, want %v",
					tc.scopes, tc.server, tc.tool, got, tc.want)
			}
		})
	}
}
