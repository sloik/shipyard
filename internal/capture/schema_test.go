package capture

import (
	"encoding/json"
	"testing"
)

func TestDiffSchemas_NoChange(t *testing.T) {
	tools := []ToolSchema{
		{Name: "read_file", Description: "Read a file", InputSchema: json.RawMessage(`{"type":"object","properties":{"path":{"type":"string"}}}`)},
		{Name: "write_file", Description: "Write a file", InputSchema: json.RawMessage(`{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}}}`)},
	}

	diff := DiffSchemas(tools, tools)
	if !diff.IsEmpty() {
		t.Fatalf("expected empty diff, got added=%d removed=%d modified=%d", len(diff.Added), len(diff.Removed), len(diff.Modified))
	}
}

func TestDiffSchemas_Added(t *testing.T) {
	before := []ToolSchema{
		{Name: "read_file", Description: "Read a file", InputSchema: json.RawMessage(`{}`)},
	}
	after := []ToolSchema{
		{Name: "read_file", Description: "Read a file", InputSchema: json.RawMessage(`{}`)},
		{Name: "write_file", Description: "Write a file", InputSchema: json.RawMessage(`{}`)},
	}

	diff := DiffSchemas(before, after)
	if len(diff.Added) != 1 {
		t.Fatalf("expected 1 added tool, got %d", len(diff.Added))
	}
	if diff.Added[0].Name != "write_file" {
		t.Fatalf("expected added tool 'write_file', got %q", diff.Added[0].Name)
	}
	if len(diff.Removed) != 0 {
		t.Fatalf("expected 0 removed, got %d", len(diff.Removed))
	}
	if len(diff.Modified) != 0 {
		t.Fatalf("expected 0 modified, got %d", len(diff.Modified))
	}
}

func TestDiffSchemas_Removed(t *testing.T) {
	before := []ToolSchema{
		{Name: "read_file", Description: "Read", InputSchema: json.RawMessage(`{}`)},
		{Name: "delete_file", Description: "Delete", InputSchema: json.RawMessage(`{}`)},
	}
	after := []ToolSchema{
		{Name: "read_file", Description: "Read", InputSchema: json.RawMessage(`{}`)},
	}

	diff := DiffSchemas(before, after)
	if len(diff.Removed) != 1 {
		t.Fatalf("expected 1 removed tool, got %d", len(diff.Removed))
	}
	if diff.Removed[0].Name != "delete_file" {
		t.Fatalf("expected removed tool 'delete_file', got %q", diff.Removed[0].Name)
	}
	if len(diff.Added) != 0 {
		t.Fatalf("expected 0 added, got %d", len(diff.Added))
	}
}

func TestDiffSchemas_Modified(t *testing.T) {
	before := []ToolSchema{
		{Name: "read_file", Description: "Read a file", InputSchema: json.RawMessage(`{"type":"object","properties":{"path":{"type":"string"}}}`)},
	}
	after := []ToolSchema{
		{Name: "read_file", Description: "Read a file", InputSchema: json.RawMessage(`{"type":"object","properties":{"path":{"type":"string"},"encoding":{"type":"string"}}}`)},
	}

	diff := DiffSchemas(before, after)
	if len(diff.Modified) != 1 {
		t.Fatalf("expected 1 modified tool, got %d", len(diff.Modified))
	}
	if diff.Modified[0].Name != "read_file" {
		t.Fatalf("expected modified tool 'read_file', got %q", diff.Modified[0].Name)
	}
}

func TestDiffSchemas_DescriptionChange(t *testing.T) {
	before := []ToolSchema{
		{Name: "read_file", Description: "Read a file", InputSchema: json.RawMessage(`{}`)},
	}
	after := []ToolSchema{
		{Name: "read_file", Description: "Read a file from disk", InputSchema: json.RawMessage(`{}`)},
	}

	diff := DiffSchemas(before, after)
	if len(diff.Modified) != 1 {
		t.Fatalf("expected 1 modified tool for description change, got %d", len(diff.Modified))
	}
}

func TestDiffSchemas_MixedChanges(t *testing.T) {
	before := []ToolSchema{
		{Name: "read_file", Description: "Read", InputSchema: json.RawMessage(`{"type":"object"}`)},
		{Name: "delete_file", Description: "Delete", InputSchema: json.RawMessage(`{}`)},
	}
	after := []ToolSchema{
		{Name: "read_file", Description: "Read", InputSchema: json.RawMessage(`{"type":"object","required":["path"]}`)},
		{Name: "write_file", Description: "Write", InputSchema: json.RawMessage(`{}`)},
	}

	diff := DiffSchemas(before, after)
	if len(diff.Added) != 1 {
		t.Fatalf("expected 1 added, got %d", len(diff.Added))
	}
	if len(diff.Removed) != 1 {
		t.Fatalf("expected 1 removed, got %d", len(diff.Removed))
	}
	if len(diff.Modified) != 1 {
		t.Fatalf("expected 1 modified, got %d", len(diff.Modified))
	}
}

func TestDiffSchemas_EmptyBefore(t *testing.T) {
	after := []ToolSchema{
		{Name: "read_file", Description: "Read", InputSchema: json.RawMessage(`{}`)},
	}

	diff := DiffSchemas(nil, after)
	if len(diff.Added) != 1 {
		t.Fatalf("expected 1 added, got %d", len(diff.Added))
	}
	if len(diff.Removed) != 0 {
		t.Fatalf("expected 0 removed, got %d", len(diff.Removed))
	}
}

func TestDiffSchemas_EmptyAfter(t *testing.T) {
	before := []ToolSchema{
		{Name: "read_file", Description: "Read", InputSchema: json.RawMessage(`{}`)},
	}

	diff := DiffSchemas(before, nil)
	if len(diff.Removed) != 1 {
		t.Fatalf("expected 1 removed, got %d", len(diff.Removed))
	}
	if len(diff.Added) != 0 {
		t.Fatalf("expected 0 added, got %d", len(diff.Added))
	}
}

func TestDiffSchemas_BothEmpty(t *testing.T) {
	diff := DiffSchemas(nil, nil)
	if !diff.IsEmpty() {
		t.Fatal("expected empty diff for nil inputs")
	}
}

func TestDiffSchemas_JSONKeyOrderInsensitive(t *testing.T) {
	before := []ToolSchema{
		{Name: "tool", Description: "d", InputSchema: json.RawMessage(`{"type":"object","properties":{"a":1,"b":2}}`)},
	}
	after := []ToolSchema{
		{Name: "tool", Description: "d", InputSchema: json.RawMessage(`{"properties":{"b":2,"a":1},"type":"object"}`)},
	}

	diff := DiffSchemas(before, after)
	if !diff.IsEmpty() {
		t.Fatal("expected no diff for equivalent JSON with different key order")
	}
}

func TestSchemaDiff_IsEmpty(t *testing.T) {
	var d SchemaDiff
	if !d.IsEmpty() {
		t.Fatal("zero-value SchemaDiff should be empty")
	}

	d.Added = []ToolSchema{{Name: "x"}}
	if d.IsEmpty() {
		t.Fatal("should not be empty with added tools")
	}
}

func TestJsonEqual_NilValues(t *testing.T) {
	if !jsonEqual(nil, nil) {
		t.Fatal("nil == nil should be true")
	}
	if !jsonEqual(nil, json.RawMessage{}) {
		t.Fatal("nil == empty should be true")
	}
	if jsonEqual(nil, json.RawMessage(`{}`)) {
		t.Fatal("nil != {} should be false")
	}
}
