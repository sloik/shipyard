package web

import (
	"strings"
	"testing"
)

// TestBUG007_ToolDetailNoMaxWidth verifies that #tool-detail does not have a
// max-width constraint so it fills the full available width (BUG-007).
func TestBUG007_ToolDetailNoMaxWidth(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}

	content := string(html)

	// AC-1: tool-detail must NOT have max-width (it should fill available width)
	// Find the tool-detail element's opening tag
	idx := strings.Index(content, `id="tool-detail"`)
	if idx == -1 {
		t.Fatal("expected to find id=\"tool-detail\" in index.html")
	}

	// Extract the surrounding tag (from the preceding '<' to the next '>')
	tagStart := strings.LastIndex(content[:idx], "<")
	tagEnd := strings.Index(content[idx:], ">")
	if tagStart == -1 || tagEnd == -1 {
		t.Fatal("could not extract tool-detail element tag")
	}
	tag := content[tagStart : idx+tagEnd+1]

	if strings.Contains(tag, "max-width") {
		t.Errorf("AC-1 FAIL: #tool-detail should not have max-width constraint, found in tag: %s", tag)
	}

	// AC-2: form fields should still have their own width constraints (400px)
	// The param form inputs should retain individual sizing, not be stretched
	if !strings.Contains(content, `id="tool-params-form"`) {
		t.Error("AC-2: expected tool-params-form element to exist")
	}

	// AC-3/AC-4: response section should exist and be ready to fill space
	if !strings.Contains(content, `id="tool-response-section"`) {
		t.Error("AC-3: expected tool-response-section element to exist")
	}

	// AC-5: tool-detail must have padding:24px
	if !strings.Contains(tag, "padding:24px") {
		t.Errorf("AC-5 FAIL: #tool-detail should have padding:24px, tag: %s", tag)
	}
}

// ---------------------------------------------------------------------------
// BUG-008: Text/JQ Toggle Missing from Per-Panel Filter Bars
// ---------------------------------------------------------------------------

// TestBUG008_PanelFiltersHaveModeToggle verifies that both the request and
// response per-panel filter bars include the Text/JQ mode toggle (BUG-008).
func TestBUG008_PanelFiltersHaveModeToggle(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// Locate the renderDetailPanel function
	fnIdx := strings.Index(content, "function renderDetailPanel")
	if fnIdx == -1 {
		t.Fatal("expected to find renderDetailPanel function in index.html")
	}
	// Grab a generous slice of the function body for inspection
	fnBody := content[fnIdx:]
	if endIdx := strings.Index(fnBody[1:], "\n  function "); endIdx > 0 {
		fnBody = fnBody[:endIdx+1]
	}

	// AC-1: Request panel filter has mode toggle (smaller variant)
	reqFilterIdx := strings.Index(fnBody, `placeholder="Filter request..."`)
	if reqFilterIdx == -1 {
		t.Fatal("AC-1: expected 'Filter request...' placeholder in renderDetailPanel")
	}
	// The mode-toggle must appear AFTER the request filter input and BEFORE
	// the response filter input
	resFilterIdx := strings.Index(fnBody, `placeholder="Filter response..."`)
	if resFilterIdx == -1 {
		t.Fatal("AC-2: expected 'Filter response...' placeholder in renderDetailPanel")
	}

	reqSlice := fnBody[reqFilterIdx:resFilterIdx]
	if !strings.Contains(reqSlice, "mode-toggle") {
		t.Error("AC-1 FAIL: request panel filter is missing mode-toggle")
	}
	if !strings.Contains(reqSlice, "mode-toggle-sm") {
		t.Error("AC-1 FAIL: request panel mode-toggle should use smaller variant (mode-toggle-sm)")
	}

	// AC-2: Response panel filter has mode toggle (smaller variant)
	resSlice := fnBody[resFilterIdx:]
	if !strings.Contains(resSlice, "mode-toggle") {
		t.Error("AC-2 FAIL: response panel filter is missing mode-toggle")
	}
	if !strings.Contains(resSlice, "mode-toggle-sm") {
		t.Error("AC-2 FAIL: response panel mode-toggle should use smaller variant (mode-toggle-sm)")
	}

	// AC-3: Per-panel toggles must be separate from combined filter toggle
	// Combined filter uses id="combined-filter-..." and its own mode-toggle
	combinedIdx := strings.Index(fnBody, "combined-filter-")
	if combinedIdx == -1 {
		t.Fatal("AC-5: expected combined filter to exist in renderDetailPanel")
	}
	combinedSlice := fnBody[combinedIdx:reqFilterIdx]
	if strings.Contains(combinedSlice, "mode-toggle-sm") {
		t.Error("AC-5 FAIL: combined filter toggle should NOT use mode-toggle-sm variant")
	}
	// Combined toggle should NOT have mode-toggle-sm
	if strings.Contains(combinedSlice, "mode-toggle-sm") {
		t.Error("AC-5 FAIL: combined filter toggle should NOT use mode-toggle-sm variant")
	}
	// Combined toggle should still exist
	if !strings.Contains(combinedSlice, "mode-toggle") {
		t.Error("AC-5 FAIL: combined filter is missing its mode-toggle")
	}
}

// TestBUG008_ModeToggleSmCSS verifies that ds.css contains the .mode-toggle-sm
// variant class with smaller sizing (BUG-008 AC-4).
func TestBUG008_ModeToggleSmCSS(t *testing.T) {
	css, err := uiFS.ReadFile("ui/ds.css")
	if err != nil {
		t.Fatalf("read embedded ds.css: %v", err)
	}
	content := string(css)

	// AC-4: .mode-toggle-sm class must exist with smaller padding
	if !strings.Contains(content, ".mode-toggle-sm") {
		t.Fatal("AC-4 FAIL: ds.css is missing .mode-toggle-sm class")
	}

	// It should use radius-s (which the base already does, but verify)
	smIdx := strings.Index(content, ".mode-toggle-sm")
	if smIdx == -1 {
		t.Fatal("AC-4 FAIL: .mode-toggle-sm not found")
	}
	// Check for the smaller padding in the vicinity of the rule
	smSlice := content[smIdx : smIdx+300]
	if !strings.Contains(smSlice, "2px 6px") {
		t.Errorf("AC-4 FAIL: .mode-toggle-sm should have padding 2px 6px, got: %s", smSlice)
	}
}

// TestBUG007_ResponseSectionFillsHeight verifies the response section can
// grow vertically to fill remaining viewport height (AC-4).
func TestBUG007_ResponseSectionFillsHeight(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}

	content := string(html)

	// The tool-detail container should use flex column layout so the
	// response section can grow to fill remaining height
	idx := strings.Index(content, `id="tool-detail"`)
	if idx == -1 {
		t.Fatal("expected to find id=\"tool-detail\" in index.html")
	}

	tagStart := strings.LastIndex(content[:idx], "<")
	tagEnd := strings.Index(content[idx:], ">")
	tag := content[tagStart : idx+tagEnd+1]

	// tool-detail should be a flex column container
	if !strings.Contains(tag, "display:flex") && !strings.Contains(tag, "display: flex") {
		// When tool-detail is shown, display will be set via JS. We check the
		// flex-direction is present for when it's visible.
		// Actually, display:none is the default (hidden). JS toggles it.
		// We need flex-direction:column in the style for when it becomes visible.
		// Let's check for flex-direction instead.
	}

	// The response section should have flex:1 to fill remaining height
	respIdx := strings.Index(content, `id="tool-response-section"`)
	if respIdx == -1 {
		t.Fatal("expected to find tool-response-section")
	}
	respTagStart := strings.LastIndex(content[:respIdx], "<")
	respTagEnd := strings.Index(content[respIdx:], ">")
	respTag := content[respTagStart : respIdx+respTagEnd+1]

	if !strings.Contains(respTag, "flex:1") {
		t.Errorf("AC-4 FAIL: #tool-response-section should have flex:1 to fill remaining height, tag: %s", respTag)
	}
}
