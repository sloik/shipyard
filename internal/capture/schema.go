package capture

import (
	"encoding/json"
)

// ToolSchema represents a single tool from a tools/list response.
type ToolSchema struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	InputSchema json.RawMessage `json:"inputSchema"`
}

// SchemaDiff describes the differences between two tool schema snapshots.
type SchemaDiff struct {
	Added    []ToolSchema       `json:"added"`
	Removed  []ToolSchema       `json:"removed"`
	Modified []ToolModification `json:"modified"`
}

// ToolModification describes a tool whose input schema changed.
type ToolModification struct {
	Name   string     `json:"name"`
	Before ToolSchema `json:"before"`
	After  ToolSchema `json:"after"`
}

// IsEmpty returns true if the diff contains no changes.
func (d SchemaDiff) IsEmpty() bool {
	return len(d.Added) == 0 && len(d.Removed) == 0 && len(d.Modified) == 0
}

// DiffSchemas compares two tool schema lists and returns the differences.
// Tools are matched by name. InputSchema is compared using JSON equality.
func DiffSchemas(before, after []ToolSchema) SchemaDiff {
	beforeMap := make(map[string]ToolSchema, len(before))
	for _, t := range before {
		beforeMap[t.Name] = t
	}
	afterMap := make(map[string]ToolSchema, len(after))
	for _, t := range after {
		afterMap[t.Name] = t
	}

	var diff SchemaDiff

	// Find added and modified
	for _, a := range after {
		b, exists := beforeMap[a.Name]
		if !exists {
			diff.Added = append(diff.Added, a)
			continue
		}
		// Compare: description change or input schema change
		if !jsonEqual(b.InputSchema, a.InputSchema) || b.Description != a.Description {
			diff.Modified = append(diff.Modified, ToolModification{
				Name:   a.Name,
				Before: b,
				After:  a,
			})
		}
	}

	// Find removed
	for _, b := range before {
		if _, exists := afterMap[b.Name]; !exists {
			diff.Removed = append(diff.Removed, b)
		}
	}

	return diff
}

// jsonEqual compares two JSON values for deep equality.
// Nil/empty values are considered equal.
func jsonEqual(a, b json.RawMessage) bool {
	// Normalize nil/empty
	if len(a) == 0 && len(b) == 0 {
		return true
	}
	if len(a) == 0 || len(b) == 0 {
		return false
	}

	// Unmarshal and re-marshal to normalize
	var aVal, bVal interface{}
	if err := json.Unmarshal(a, &aVal); err != nil {
		return false
	}
	if err := json.Unmarshal(b, &bVal); err != nil {
		return false
	}

	aNorm, err := json.Marshal(aVal)
	if err != nil {
		return false
	}
	bNorm, err := json.Marshal(bVal)
	if err != nil {
		return false
	}

	return string(aNorm) == string(bNorm)
}

// SchemaChange represents a schema change record for the API.
type SchemaChange struct {
	ID            int64  `json:"id"`
	ServerName    string `json:"server_name"`
	DetectedAt    string `json:"detected_at"`
	ToolsAdded    int    `json:"tools_added"`
	ToolsRemoved  int    `json:"tools_removed"`
	ToolsModified int    `json:"tools_modified"`
	Acknowledged  bool   `json:"acknowledged"`
}

// SchemaChangeDetail includes the full diff JSON.
type SchemaChangeDetail struct {
	SchemaChange
	DiffJSON SchemaDiff `json:"diff"`
}
