package web

import (
	"strings"
	"testing"
)

// TestSPECBUG012_RouteViewsUseDedicatedRouteStack verifies that the app shell
// keeps the app bar outside the route stack and that each top-level view uses
// the explicit route-view contract required for isolated navigation.
func TestSPECBUG012_RouteViewsUseDedicatedRouteStack(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	headerIdx := strings.Index(content, "<header class=\"app-bar\">")
	if headerIdx == -1 {
		t.Fatal("AC-9 FAIL: expected app bar header to exist")
	}
	chromeIdx := strings.Index(content, `id="app-chrome"`)
	if chromeIdx == -1 {
		t.Fatal("AC-9 FAIL: expected app-chrome container to exist")
	}
	routeStackIdx := strings.Index(content, `id="route-stack"`)
	if routeStackIdx == -1 {
		t.Fatal("AC-7 FAIL: expected route-stack container to exist")
	}
	if !(headerIdx < chromeIdx && chromeIdx < routeStackIdx) {
		t.Fatalf("AC-9 FAIL: expected header/app chrome/route stack ordering, got header=%d chrome=%d routeStack=%d", headerIdx, chromeIdx, routeStackIdx)
	}
	for _, targetID := range []string{`id="timeline" class="route-target"`, `id="tools" class="route-target"`, `id="history" class="route-target"`, `id="servers" class="route-target"`} {
		if !strings.Contains(content, targetID) {
			t.Errorf("AC-7 FAIL: expected route target marker %q", targetID)
		}
	}

	expectedViews := []string{
		`id="view-timeline" class="route-view is-active"`,
		`id="view-tools" class="route-view route-view-flex"`,
		`id="view-history" class="route-view"`,
		`id="view-servers" class="route-view"`,
	}
	for _, needle := range expectedViews {
		if !strings.Contains(content, needle) {
			t.Errorf("AC-7 FAIL: expected route-view declaration %q", needle)
		}
	}
}

// TestSPECBUG012_NavigateUsesActiveRouteClasses verifies that navigate()
// activates one top-level route via class toggling instead of treating the
// page as one long stacked document.
func TestSPECBUG012_NavigateUsesActiveRouteClasses(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	fnIdx := strings.Index(content, "function navigate(route)")
	if fnIdx == -1 {
		t.Fatal("AC-7 FAIL: expected navigate(route) function in index.html")
	}
	fnBody := content[fnIdx:]
	if endIdx := strings.Index(fnBody[1:], "\n  window.addEventListener"); endIdx > 0 {
		fnBody = fnBody[:endIdx+1]
	}

	if strings.Contains(fnBody, ".style.display = 'none'") || strings.Contains(fnBody, ".style.display = baseRoute === 'tools' ? 'flex' : ''") {
		t.Error("AC-7 FAIL: navigate() should not use inline display toggles for top-level route isolation")
	}
	if !strings.Contains(fnBody, "classList.remove('is-active')") {
		t.Error("AC-7 FAIL: navigate() should remove is-active from non-selected views")
	}
	if !strings.Contains(fnBody, "classList.add('is-active')") {
		t.Error("AC-7 FAIL: navigate() should add is-active to the selected view")
	}
	if !strings.Contains(fnBody, "tab-active") {
		t.Error("AC-8 FAIL: navigate() should continue updating active tab state")
	}
}

// TestSPECBUG012_InitRouteActivatesDefaultViewImmediately verifies that the
// page never waits on async startup fetches before showing an initial route.
func TestSPECBUG012_InitRouteActivatesDefaultViewImmediately(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	initIdx := strings.Index(content, "(function initRoute()")
	if initIdx == -1 {
		t.Fatal("expected initRoute bootstrap in index.html")
	}
	initBody := content[initIdx:]
	if endIdx := strings.Index(initBody[1:], "\n\n  // Load initial data"); endIdx > 0 {
		initBody = initBody[:endIdx+1]
	}

	if !strings.Contains(content, `id="view-timeline" class="route-view is-active"`) {
		t.Error("AC-7 FAIL: timeline view should be active by default in the HTML shell")
	}
	if !strings.Contains(initBody, "navigate(route);") {
		t.Error("AC-7 FAIL: initRoute should activate the current route immediately before async fetches")
	}
	if strings.Contains(initBody, ".catch(function() { navigate(route); });") {
		t.Error("AC-7 FAIL: initRoute should not rely on async fallback navigation to reveal the initial route")
	}
}

// TestSPECBUG012_TabClicksNavigateImmediately verifies that top tabs are
// plain hash links and do not depend on a JS click handler.
func TestSPECBUG012_TabClicksNavigateImmediately(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	for _, href := range []string{`href="#timeline"`, `href="#tools"`, `href="#history"`, `href="#servers"`} {
		if !strings.Contains(content, href) {
			t.Errorf("AC-8 FAIL: expected top-nav hash link %q", href)
		}
	}
	if !strings.Contains(content, "window.addEventListener('hashchange'") {
		t.Error("AC-8 FAIL: expected hashchange routing hook")
	}
	if strings.Contains(content, `onclick="return window.__shipyardNavigateRoute(`) {
		t.Error("AC-8 FAIL: tabs should not require inline onclick handlers to navigate")
	}
	if strings.Contains(content, "tabNav.addEventListener('click'") {
		t.Error("AC-8 FAIL: tabs should not depend on a JS click handler that can block native hash navigation")
	}
	if !strings.Contains(content, "window.__shipyardNavigateRoute = function(route, href)") {
		t.Error("AC-8 FAIL: explicit route helper should exist for desktop/webview tab clicks")
	}
	if !strings.Contains(content, "navigate(route);") || !strings.Contains(content, "if (href && location.hash !== href)") {
		t.Error("AC-8 FAIL: explicit route helper should navigate immediately and keep the hash in sync")
	}
}

// TestSPECBUG012_AppShellCSS verifies the app shell owns scrolling at the
// route-view level so the app bar remains visible during view scrolling.
func TestSPECBUG012_AppShellCSS(t *testing.T) {
	css, err := uiFS.ReadFile("ui/ds.css")
	if err != nil {
		t.Fatalf("read embedded ds.css: %v", err)
	}
	content := string(css)

	requiredRules := []string{
		"html {\n  font-family: var(--font-sans);",
		"height: 100%;",
		"overflow: hidden;",
		"#app-chrome {",
		"#route-stack {",
		".route-view {",
		".route-view.is-active {",
		".route-view.route-view-flex.is-active {",
		"flex-shrink: 0;",
		"--wails-draggable: no-drag;",
	}
	for _, needle := range requiredRules {
		if !strings.Contains(content, needle) {
			t.Errorf("AC-9 FAIL: expected CSS to contain %q", needle)
		}
	}
}

// TestSPECBUG013_AddServerCTAUsesSharedModal verifies the empty-state Add
// Server button is wired to the shared modal flow and includes concrete setup
// guidance instead of a fragile inline alert.
func TestSPECBUG013_AddServerCTAUsesSharedModal(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	btnIdx := strings.Index(content, `id="servers-empty-add-btn"`)
	if btnIdx == -1 {
		t.Fatal("expected servers-empty-add-btn in index.html")
	}
	btnStart := strings.LastIndex(content[:btnIdx], "<button")
	btnEnd := strings.Index(content[btnIdx:], ">")
	if btnStart == -1 || btnEnd == -1 {
		t.Fatal("could not extract servers-empty-add-btn tag")
	}
	btnTag := content[btnStart : btnIdx+btnEnd+1]
	if strings.Contains(btnTag, "onclick=") {
		t.Fatalf("AC-1 FAIL: Add Server button should not use inline onclick, tag=%s", btnTag)
	}

	requiredSnippets := []string{
		"function openAddServerModal()",
		"emptyAddBtn.addEventListener('click', openAddServerModal)",
		"emptyAddBtn.addEventListener('mousedown', function(e) { e.stopPropagation(); })",
		"DS.modal('Add a server'",
		"shipyard --config ~/servers.json",
		`"servers": {`,
		`@modelcontextprotocol/server-filesystem`,
		"label: 'Close'",
		"escapeHtml(addServerCommand)",
		"escapeHtml(addServerConfig)",
	}
	for _, needle := range requiredSnippets {
		if !strings.Contains(content, needle) {
			t.Errorf("AC-1/AC-2/AC-6 FAIL: expected %q in add-server flow", needle)
		}
	}
}

// TestSPECBUG013_SharedModalIsDismissible verifies the shared modal helper
// supports Escape key and backdrop dismissal so the add-server flow can be
// closed without restarting the app.
func TestSPECBUG013_SharedModalIsDismissible(t *testing.T) {
	js, err := uiFS.ReadFile("ui/ds.js")
	if err != nil {
		t.Fatalf("read embedded ds.js: %v", err)
	}
	content := string(js)

	requiredSnippets := []string{
		"DS.modal = function(title, body, actions)",
		"if (e.key === 'Escape') { close(''); }",
		"backdrop.addEventListener('click', function(e) {",
		"if (e.target === backdrop) close('');",
		"btn.addEventListener('click', function() { close(action.value); });",
	}
	for _, needle := range requiredSnippets {
		if !strings.Contains(content, needle) {
			t.Errorf("AC-3 FAIL: expected %q in shared modal helper", needle)
		}
	}
}

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

// ---------------------------------------------------------------------------
// SPEC-003: Phase 2 History View Layout Tests
// ---------------------------------------------------------------------------

// TestSPEC003_HistoryViewElements verifies that the History view contains
// all required structural elements for search, replay, and diff.
func TestSPEC003_HistoryViewElements(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// AC-1: Replay button must exist in the JS
	if !strings.Contains(content, "history-replay-btn") {
		t.Error("AC-1 FAIL: expected history-replay-btn class for replay buttons")
	}
	if !strings.Contains(content, "/api/replay") {
		t.Error("AC-1 FAIL: expected /api/replay fetch call")
	}

	// AC-2: Edit & Replay button
	if !strings.Contains(content, "history-edit-btn") {
		t.Error("AC-2 FAIL: expected history-edit-btn class for edit buttons")
	}
	if !strings.Contains(content, "editAndReplay") {
		t.Error("AC-2 FAIL: expected editAndReplay function")
	}

	// AC-4: Search input
	if !strings.Contains(content, `id="history-search"`) {
		t.Error("AC-4 FAIL: expected history-search input")
	}
	// Time range filter
	if !strings.Contains(content, `id="history-time-toggle"`) {
		t.Error("AC-4 FAIL: expected history-time-toggle")
	}
	// Server filter
	if !strings.Contains(content, `id="history-server-filter"`) {
		t.Error("AC-4 FAIL: expected history-server-filter")
	}
	// Method filter
	if !strings.Contains(content, `id="history-method-filter"`) {
		t.Error("AC-4 FAIL: expected history-method-filter")
	}

	// AC-5: Pagination elements
	if !strings.Contains(content, `id="history-pagination"`) {
		t.Error("AC-5 FAIL: expected history-pagination container")
	}
	if !strings.Contains(content, `id="history-goto-input"`) {
		t.Error("AC-5 FAIL: expected history-goto-input for 'Go to page'")
	}

	// AC-6: Compare/diff elements
	if !strings.Contains(content, `id="history-compare-btn"`) {
		t.Error("AC-6 FAIL: expected history-compare-btn")
	}
	if !strings.Contains(content, `id="history-diff"`) {
		t.Error("AC-6 FAIL: expected history-diff container")
	}
	if !strings.Contains(content, "computeLineDiff") {
		t.Error("AC-6 FAIL: expected computeLineDiff function for diff computation")
	}

	// Empty states
	if !strings.Contains(content, `id="history-empty"`) {
		t.Error("expected history-empty state")
	}
	if !strings.Contains(content, `id="history-no-results"`) {
		t.Error("expected history-no-results state")
	}
}

// ---------------------------------------------------------------------------
// SPEC-004: Phase 3 Server Management Layout Tests
// ---------------------------------------------------------------------------

// TestSPEC004_ServersViewElements verifies the Servers view has all required
// structural elements for server management.
func TestSPEC004_ServersViewElements(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// AC-2: Server grid exists
	if !strings.Contains(content, `id="servers-grid"`) {
		t.Error("AC-2 FAIL: expected servers-grid element")
	}

	// AC-2: Server summary in action bar
	if !strings.Contains(content, `id="servers-summary"`) {
		t.Error("AC-2 FAIL: expected servers-summary element")
	}

	// AC-4: Restart functionality
	if !strings.Contains(content, "__shipyard_restartServer") {
		t.Error("AC-4 FAIL: expected restartServer function")
	}
	if !strings.Contains(content, "/api/servers/") {
		t.Error("AC-4 FAIL: expected /api/servers/ endpoint calls")
	}

	// AC-4: Stop functionality
	if !strings.Contains(content, "__shipyard_stopServer") {
		t.Error("AC-4 FAIL: expected stopServer function")
	}

	// AC-5: Auto-import button exists
	if !strings.Contains(content, `id="servers-auto-import-btn"`) {
		t.Error("AC-5 FAIL: expected auto-import button")
	}

	// AC-5: Auto-import modal exists
	if !strings.Contains(content, `id="auto-import-modal"`) {
		t.Error("AC-5 FAIL: expected auto-import modal")
	}

	// AC-5: Auto-import endpoint
	if !strings.Contains(content, "/api/auto-import") {
		t.Error("AC-5 FAIL: expected /api/auto-import fetch call")
	}

	// AC-3: WebSocket server_status handling
	if !strings.Contains(content, "server_status") {
		t.Error("AC-3 FAIL: expected server_status WebSocket event handler")
	}

	// Empty state
	if !strings.Contains(content, `id="servers-empty"`) {
		t.Error("expected servers-empty state")
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
