package auth

import (
	"strings"
	"testing"
)

func FuzzMatchScopeDenyByDefault(f *testing.F) {
	for _, seed := range []struct{ server, tool, otherServer, otherTool string }{
		{"filesystem", "read_file", "cortex", "cortex_search"},
		{"unicode_żółw", "tool_世界", "other", "tool"},
		{"boundary", strings.Repeat("x", 128), "unrelated", "write_file"},
	} {
		f.Add(seed.server, seed.tool, seed.otherServer, seed.otherTool)
	}

	f.Fuzz(func(t *testing.T, server, tool, otherServer, otherTool string) {
		if len(server)+len(tool)+len(otherServer)+len(otherTool) > 4096 {
			t.Skip()
		}
		server = scopeAtom(server)
		tool = scopeAtom(tool)
		otherServer = scopeAtom(otherServer)
		otherTool = scopeAtom(otherTool)
		if otherServer == server && otherTool == tool {
			otherTool += "_other"
		}

		exactScope := server + ":" + tool
		if !MatchScope([]string{exactScope}, server, tool) {
			t.Fatalf("exact scope %q did not authorize its tool", exactScope)
		}
		if MatchScope([]string{exactScope}, otherServer, otherTool) {
			t.Fatalf("narrower scope %q authorized unrelated %s:%s", exactScope, otherServer, otherTool)
		}
		if MatchScope([]string{server + ":*"}, otherServer, otherTool) && otherServer != server {
			t.Fatalf("server wildcard authorized unrelated server %q", otherServer)
		}
	})
}

func scopeAtom(value string) string {
	value = strings.Map(func(r rune) rune {
		switch r {
		case ':', '*', '?', '[', ']', '\\':
			return -1
		default:
			return r
		}
	}, value)
	if value == "" {
		return "empty"
	}
	return value
}
