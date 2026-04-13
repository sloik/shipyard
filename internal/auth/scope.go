package auth

import "path"

// MatchScope reports whether a tool identified as "server:tool" matches any
// of the provided scope patterns. Each pattern is in "{server_pattern}:{tool_pattern}"
// format. Both halves use path.Match glob semantics.
//
// Special case: a wildcard-only pattern "*" matches everything.
func MatchScope(scopes []string, server, tool string) bool {
	for _, pattern := range scopes {
		if matchScopePattern(pattern, server, tool) {
			return true
		}
	}
	return false
}

// matchScopePattern checks a single scope pattern against a server:tool pair.
func matchScopePattern(pattern, server, tool string) bool {
	// Find the colon separator
	colonIdx := -1
	for i, c := range pattern {
		if c == ':' {
			colonIdx = i
			break
		}
	}

	if colonIdx < 0 {
		// No colon: treat as server-only wildcard matching everything
		// (shouldn't normally happen, but don't panic)
		ok, _ := path.Match(pattern, server)
		return ok
	}

	serverPat := pattern[:colonIdx]
	toolPat := pattern[colonIdx+1:]

	serverOk, _ := path.Match(serverPat, server)
	if !serverOk {
		return false
	}
	toolOk, _ := path.Match(toolPat, tool)
	return toolOk
}
