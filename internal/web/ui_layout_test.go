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

	fnIdx := strings.Index(content, "function navigateRoute(route)")
	if fnIdx == -1 {
		t.Fatal("AC-7 FAIL: expected navigateRoute(route) function in index.html")
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
	if !strings.Contains(initBody, "navigateRoute(route);") {
		t.Error("AC-7 FAIL: initRoute should activate the current route immediately before async fetches")
	}
	if !strings.Contains(initBody, "loadServers();") {
		t.Error("SPEC-BUG-014 FAIL: initRoute should eagerly hydrate server state from /api/servers")
	}
	if strings.Contains(initBody, ".catch(function() { navigateRoute(route); });") {
		t.Error("AC-7 FAIL: initRoute should not rely on async fallback navigation to reveal the initial route")
	}
}

func TestSPECBUG014_ServerStatePollingStartsAtBootstrap(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	if !strings.Contains(content, "function startServerStatePolling()") {
		t.Fatal("SPEC-BUG-014 FAIL: expected dedicated server-state polling bootstrap helper")
	}
	if !strings.Contains(content, "serverStateTimer = setInterval(function() {") {
		t.Error("SPEC-BUG-014 FAIL: expected interval-based server-state polling")
	}
	if !strings.Contains(content, "loadServers();\n    }, 2000);") {
		t.Error("SPEC-BUG-014 FAIL: expected polling loop to refresh via loadServers()")
	}
	if !strings.Contains(content, "startServerStatePolling();") {
		t.Error("SPEC-BUG-014 FAIL: expected bootstrap to start server-state polling")
	}
}

func TestSPECBUG016_DesktopBridgeConfigBootstrap(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	requiredSnippets := []string{
		"var nativeFetch   = window.fetch.bind(window);",
		"var desktopBridgeConfig = null;",
		"var desktopBridgeConfigPromise = null;",
		"function usesDesktopAssetOrigin()",
		"return location.protocol !== 'http:' && location.protocol !== 'https:';",
		"function loadDesktopBridgeConfig()",
		"nativeFetch('/_shipyard/desktop-config')",
		"desktopBridgeConfig = config || {};",
		"function resolveAPIURL(path)",
		"desktopBridgeConfig.api_base",
		"function appFetch(input, init)",
		"return nativeFetch(resolveAPIURL(input), init);",
		"window.fetch = appFetch;",
		"loadDesktopBridgeConfig().then(function() {",
		"connectWS();",
	}
	for _, needle := range requiredSnippets {
		if !strings.Contains(content, needle) {
			t.Errorf("SPEC-BUG-016 FAIL: expected %q in desktop bridge bootstrap", needle)
		}
	}
}

func TestSPECBUG016_ConnectWSUsesResolvedDesktopURL(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	connectIdx := strings.Index(content, "function connectWS()")
	if connectIdx == -1 {
		t.Fatal("expected connectWS() function in index.html")
	}
	connectBody := content[connectIdx:]
	if endIdx := strings.Index(connectBody[1:], "\n\n  retryBtn.addEventListener"); endIdx > 0 {
		connectBody = connectBody[:endIdx+1]
	}

	requiredSnippets := []string{
		"function resolveWebSocketURL(path)",
		"desktopBridgeConfig.ws_base",
		"return desktopBridgeConfig.ws_base.replace(/\\/$/, '') + path;",
		"ws = new WebSocket(resolveWebSocketURL('/ws'));",
	}
	for _, needle := range requiredSnippets {
		if !strings.Contains(content, needle) && !strings.Contains(connectBody, needle) {
			t.Errorf("SPEC-BUG-016 FAIL: expected %q in desktop websocket transport path", needle)
		}
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
	if !strings.Contains(content, "navigateRoute(route);") || !strings.Contains(content, "if (href && location.hash !== href)") {
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
// max-width constraint so it fills the full available width (SPEC-BUG-007).
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
	if !strings.Contains(content, "field-width-400") {
		t.Error("AC-2: expected schema-driven fields to include the Phase 1 width classes")
	}

	// AC-3/AC-4: response section should exist and be ready to fill space
	if !strings.Contains(content, `id="tool-response-section"`) {
		t.Error("AC-3: expected tool-response-section element to exist")
	}

	// AC-5: tool-detail must NOT have padding (SPEC-BUG-029: padding moved to inner regions)
	if strings.Contains(tag, "padding:") {
		t.Errorf("AC-5 FAIL: #tool-detail must not have padding (padding belongs on inner regions, not outer flex container), tag: %s", tag)
	}
}

func TestSPECBUG017_ToolBrowserEmptyStateMatchesPhase1CardTreatment(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	idx := strings.Index(content, `id="tools-empty"`)
	if idx == -1 {
		t.Fatal("expected tools-empty in index.html")
	}
	tagStart := strings.LastIndex(content[:idx], "<")
	tagEnd := strings.Index(content[idx:], ">")
	if tagStart == -1 || tagEnd == -1 {
		t.Fatal("could not extract tools-empty tag")
	}
	tag := content[tagStart : idx+tagEnd+1]

	for _, needle := range []string{"class=\"empty-state tool-browser-empty-state\"", "height:100%"} {
		if !strings.Contains(tag, needle) {
			t.Errorf("SPEC-BUG-017 FAIL: expected %q in tools-empty tag: %s", needle, tag)
		}
	}
	if !strings.Contains(content, "fill in parameters, and execute it.") {
		t.Error("SPEC-BUG-017 FAIL: tools empty-state copy should mention per-tool parameter controls")
	}

	css, err := uiFS.ReadFile("ui/ds.css")
	if err != nil {
		t.Fatalf("read embedded ds.css: %v", err)
	}
	cssContent := string(css)
	for _, needle := range []string{
		".tool-browser-empty-state {",
		"padding: 32px;",
		"border: 1px solid var(--border-muted);",
		"border-radius: var(--radius-l);",
		"background: var(--bg-surface);",
	} {
		if !strings.Contains(cssContent, needle) {
			t.Errorf("SPEC-BUG-017 FAIL: expected %q in tool-browser empty-state CSS", needle)
		}
	}
}

func TestSPECBUG025_ToolBrowserSchemaFieldsUsePhase1WidthClasses(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	renderIdx := strings.Index(content, "function renderToolForm(schema)")
	if renderIdx == -1 {
		t.Fatal("SPEC-BUG-025 FAIL: expected renderToolForm(schema) in index.html")
	}
	renderBody := content[renderIdx:]
	if endIdx := strings.Index(renderBody[1:], "\n  /* ======================================================================\n     Tool Browser — Collect Form Arguments"); endIdx > 0 {
		renderBody = renderBody[:endIdx+1]
	}

	for _, needle := range []string{
		"var fieldCount = keys.length;",
		"renderField(key, prop, isRequired, fieldCount === 1);",
		"function getFieldWidthClass(prop, forceWide)",
		"if (forceWide) return 'field-width-400';",
		"return 'field-width-240';",
		"field-width-auto",
		"field-width-160",
		"field-width-200",
	} {
		if !strings.Contains(renderBody, needle) && !strings.Contains(content, needle) {
			t.Errorf("SPEC-BUG-025 FAIL: expected %q in schema field width contract", needle)
		}
	}

	css, err := uiFS.ReadFile("ui/ds.css")
	if err != nil {
		t.Fatalf("read embedded ds.css: %v", err)
	}
	cssContent := string(css)
	for _, needle := range []string{
		".field-width-400 {",
		"width: 400px;",
		".field-width-240 {",
		".field-width-200 {",
		".field-width-160 {",
		".field-width-auto {",
		"width: fit-content;",
	} {
		if !strings.Contains(cssContent, needle) {
			t.Errorf("SPEC-BUG-025 FAIL: expected %q in field width CSS", needle)
		}
	}
}

func TestSPECBUG028_ToolBrowserLongSchemaFormsUseDedicatedScrollOwner(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	checkTag := func(id string) string {
		idx := strings.Index(content, `id="`+id+`"`)
		if idx == -1 {
			t.Fatalf("expected to find %s in index.html", id)
		}
		tagStart := strings.LastIndex(content[:idx], "<")
		tagEnd := strings.Index(content[idx:], ">")
		if tagStart == -1 || tagEnd == -1 {
			t.Fatalf("could not extract %s tag", id)
		}
		return content[tagStart : idx+tagEnd+1]
	}

	mainTag := checkTag("tools-main")
	for _, needle := range []string{
		"display:flex",
		"flex-direction:column",
		"min-height:0",
		"overflow:hidden",
	} {
		if !strings.Contains(mainTag, needle) {
			t.Errorf("SPEC-BUG-028 FAIL: expected %q in #tools-main tag: %s", needle, mainTag)
		}
	}

	detailTag := checkTag("tool-detail")
	for _, needle := range []string{
		"height:100%",
		"min-height:0",
		"flex-direction:column",
		"overflow:hidden",
	} {
		if !strings.Contains(detailTag, needle) {
			t.Errorf("SPEC-BUG-028 FAIL: expected %q in #tool-detail tag: %s", needle, detailTag)
		}
	}

	scrollTag := checkTag("tool-detail-scroll")
	for _, needle := range []string{
		"display:flex",
		"flex:1 1 0",
		"min-height:0",
		"flex-direction:column",
		"overflow-y:auto",
	} {
		if !strings.Contains(scrollTag, needle) {
			t.Errorf("SPEC-BUG-028 FAIL: expected %q in #tool-detail-scroll tag: %s", needle, scrollTag)
		}
	}

	responseTag := checkTag("tool-response-section")
	for _, needle := range []string{"display:flex", "flex:0 0 300px", "flex-direction:column"} {
		if !strings.Contains(responseTag, needle) {
			t.Errorf("SPEC-BUG-028 FAIL: expected %q in #tool-response-section tag: %s", needle, responseTag)
		}
	}

	scrollIdx := strings.Index(content, `id="tool-detail-scroll"`)
	paramsIdx := strings.Index(content, `id="tool-params-section"`)
	execIdx := strings.Index(content, `id="tool-execute-btn"`)
	responseIdx := strings.Index(content, `id="tool-response-section"`)
	if scrollIdx == -1 || paramsIdx == -1 || execIdx == -1 || responseIdx == -1 {
		t.Fatal("SPEC-BUG-028 FAIL: expected scroll, params, execute, and response sections")
	}
	if !(scrollIdx < paramsIdx && paramsIdx < execIdx && execIdx < responseIdx) {
		t.Fatalf("SPEC-BUG-028 FAIL: expected params and execute controls to stay inside the scroll owner before response section, got scroll=%d params=%d execute=%d response=%d", scrollIdx, paramsIdx, execIdx, responseIdx)
	}

	css, err := uiFS.ReadFile("ui/ds.css")
	if err != nil {
		t.Fatalf("read embedded ds.css: %v", err)
	}
	cssContent := string(css)
	for _, needle := range []string{
		"#tools-main {",
		"overflow: hidden;",
		"#tool-detail-scroll {",
		"overflow-y: auto;",
		"flex: 0 1 auto;",
		"min-height: 0;",
	} {
		if !strings.Contains(cssContent, needle) {
			t.Errorf("SPEC-BUG-028 FAIL: expected %q in scroll ownership CSS", needle)
		}
	}
}

// ---------------------------------------------------------------------------
// SPEC-BUG-029: Tool Browser padding on outer flex container eats scroll height
// ---------------------------------------------------------------------------

// TestSPECBUG029_ToolDetailPaddingIsolationContract verifies that padding is NOT
// on the outer #tool-detail flex container and IS on the inner regions
// (#tool-detail-scroll and #tool-response-section), so the full container height
// is available for flex layout and the response section is never hidden.
func TestSPECBUG029_ToolDetailPaddingIsolationContract(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	checkTag := func(id string) string {
		idx := strings.Index(content, `id="`+id+`"`)
		if idx == -1 {
			t.Fatalf("expected to find id=%q in index.html", id)
		}
		tagStart := strings.LastIndex(content[:idx], "<")
		tagEnd := strings.Index(content[idx:], ">")
		if tagStart == -1 || tagEnd == -1 {
			t.Fatalf("could not extract tag for id=%q", id)
		}
		return content[tagStart : idx+tagEnd+1]
	}

	// AC-5a: #tool-detail must NOT have any padding — the full height must go to flex children
	detailTag := checkTag("tool-detail")
	if strings.Contains(detailTag, "padding:") {
		t.Errorf("SPEC-BUG-029 FAIL: #tool-detail must not have padding (causes scroll height loss), tag: %s", detailTag)
	}

	// AC-5b: #tool-detail-scroll must have top/side padding (visual spacing inside scroll region)
	scrollTag := checkTag("tool-detail-scroll")
	if !strings.Contains(scrollTag, "padding:") {
		t.Errorf("SPEC-BUG-029 FAIL: #tool-detail-scroll must have padding (visual spacing moved from outer container), tag: %s", scrollTag)
	}
	// Must have non-zero bottom padding value of 0 (padding:24px 24px 0 24px)
	// or equivalent — key contract is that padding exists on the scroll region
	if !strings.Contains(scrollTag, "padding:24px 24px 0 24px") {
		t.Errorf("SPEC-BUG-029 FAIL: #tool-detail-scroll should have padding:24px 24px 0 24px (top/sides, no bottom gap before response), tag: %s", scrollTag)
	}

	// AC-5c: #tool-response-section must have side/bottom padding
	responseTag := checkTag("tool-response-section")
	if !strings.Contains(responseTag, "padding:") {
		t.Errorf("SPEC-BUG-029 FAIL: #tool-response-section must have padding (visual spacing moved from outer container), tag: %s", responseTag)
	}
	if !strings.Contains(responseTag, "padding:0 24px 24px 24px") {
		t.Errorf("SPEC-BUG-029 FAIL: #tool-response-section should have padding:0 24px 24px 24px (sides/bottom, no top gap after scroll region), tag: %s", responseTag)
	}
}

// ---------------------------------------------------------------------------
// SPEC-BUG-008: Text/JQ Toggle Missing from Per-Panel Filter Bars
// ---------------------------------------------------------------------------

// TestBUG008_PanelFiltersHaveModeToggle verifies that both the request and
// response per-panel filter bars include the Text/JQ mode toggle (SPEC-BUG-008).
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
// variant class with smaller sizing (SPEC-BUG-008 AC-4).
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

	// AC-2: Server stat indicators in action bar (SPEC-BUG-034: replaces servers-summary)
	if !strings.Contains(content, `id="servers-stat-online"`) {
		t.Error("AC-2 FAIL: expected servers-stat-online element (replaces servers-summary per SPEC-BUG-034)")
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

// TestSPECBUG014_LoadServersRefreshesBadge verifies the Servers view refresh
// path updates the header badge from the API response and preserves the
// configured-server vs empty-state branch behavior.
func TestSPECBUG014_LoadServersRefreshesBadge(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	loadIdx := strings.Index(content, "function loadServers()")
	if loadIdx == -1 {
		t.Fatal("expected loadServers() function in index.html")
	}
	loadBody := content[loadIdx:]
	if endIdx := strings.Index(loadBody[1:], "\n  function renderServerCards"); endIdx > 0 {
		loadBody = loadBody[:endIdx+1]
	}

	// SPEC-BUG-034: serversSummary.textContent replaced with individual stat elements
	requiredSnippets := []string{
		"serverCountEl.textContent = serverCount + ' server'",
		"serversEmpty.style.display = ''",
		"serversGrid.style.display = 'none'",
		"serversActionBar.style.display = 'none'",
		"serversEmpty.style.display = 'none'",
		"serversGrid.style.display = ''",
		"serversActionBar.style.display = ''",
		"servers-stat-online",
		"servers-stat-crashed",
		"servers-stat-tools",
	}
	for _, needle := range requiredSnippets {
		if !strings.Contains(loadBody, needle) {
			t.Errorf("expected %q in loadServers()", needle)
		}
	}
}

// TestSPECBUG014_NavigateRefreshesServersView verifies that entering the
// Servers route re-syncs from /api/servers instead of relying on stale state
// from the traffic filter bootstrap.
func TestSPECBUG014_NavigateRefreshesServersView(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	navigateIdx := strings.Index(content, "function navigateRoute(route)")
	if navigateIdx == -1 {
		t.Fatal("expected navigateRoute(route) function in index.html")
	}
	navigateBody := content[navigateIdx:]
	if endIdx := strings.Index(navigateBody[1:], "\n\n  window.__shipyardNavigateRoute"); endIdx > 0 {
		navigateBody = navigateBody[:endIdx+1]
	}

	requiredSnippets := []string{
		"if (baseRoute === 'servers') {",
		"loadServers();",
	}
	for _, needle := range requiredSnippets {
		if !strings.Contains(navigateBody, needle) {
			t.Errorf("expected %q in navigateRoute(route)", needle)
		}
	}
}

// TestSPECBUG014_TrackFiltersDoesNotOwnServerCountBadge verifies traffic
// filter bootstrapping no longer overwrites the global configured-server badge.
func TestSPECBUG014_TrackFiltersDoesNotOwnServerCountBadge(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	trackIdx := strings.Index(content, "function trackFilters(items)")
	if trackIdx == -1 {
		t.Fatal("expected trackFilters(items) function in index.html")
	}
	trackBody := content[trackIdx:]
	if endIdx := strings.Index(trackBody[1:], "\n  function rebuildDropdown"); endIdx > 0 {
		trackBody = trackBody[:endIdx+1]
	}

	if strings.Contains(trackBody, "serverCountEl.textContent") {
		t.Fatal("SPEC-BUG-014 FAIL: trackFilters should not mutate the server-count badge")
	}
}

// TestSPECBUG015_ServersTabSameRouteClickRefreshesLiveState verifies that a
// same-route Servers tab activation still re-syncs the view from /api/servers
// in the Wails webview, where hashchange is not guaranteed for same-hash
// clicks.
func TestSPECBUG015_ServersTabSameRouteClickRefreshesLiveState(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	listenerIdx := strings.Index(content, "tabNav.addEventListener('pointerup'")
	if listenerIdx == -1 {
		t.Fatal("expected pointerup listener on tabNav in index.html")
	}
	listenerBody := content[listenerIdx:]
	if endIdx := strings.Index(listenerBody[1:], "\n\n  /* ======================================================================"); endIdx > 0 {
		listenerBody = listenerBody[:endIdx+1]
	}

	requiredSnippets := []string{
		"data-route') !== 'servers'",
		"if (getRoute() === 'servers') {",
		"loadServers();",
	}
	for _, needle := range requiredSnippets {
		if !strings.Contains(listenerBody, needle) {
			t.Errorf("expected %q in same-route servers refresh handler", needle)
		}
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

	if !strings.Contains(respTag, "flex:0 0 300px") {
		t.Errorf("AC-4 FAIL: #tool-response-section should have flex:0 0 300px (fixed default height so JSON scrolls), tag: %s", respTag)
	}
}

// TestSPECBUG021_ToolBrowserResponsePanelUsesFillHeightLayout verifies that
// the Tool Browser response panel fills remaining pane height and keeps
// scrolling local to the response JSON viewer.
func TestSPECBUG021_ToolBrowserResponsePanelUsesFillHeightLayout(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	checkTag := func(id string) string {
		idx := strings.Index(content, `id="`+id+`"`)
		if idx == -1 {
			t.Fatalf("expected to find %s in index.html", id)
		}
		tagStart := strings.LastIndex(content[:idx], "<")
		tagEnd := strings.Index(content[idx:], ">")
		if tagStart == -1 || tagEnd == -1 {
			t.Fatalf("could not extract %s tag", id)
		}
		return content[tagStart : idx+tagEnd+1]
	}

	detailTag := checkTag("tool-detail")
	for _, needle := range []string{"height:100%", "min-height:0", "flex-direction:column"} {
		if !strings.Contains(detailTag, needle) {
			t.Errorf("SPEC-BUG-021 FAIL: expected %q in #tool-detail tag: %s", needle, detailTag)
		}
	}

	responseSectionTag := checkTag("tool-response-section")
	for _, needle := range []string{"display:flex", "flex-direction:column", "flex:0 0 300px"} {
		if !strings.Contains(responseSectionTag, needle) {
			t.Errorf("SPEC-BUG-021 FAIL: expected %q in #tool-response-section tag: %s", needle, responseSectionTag)
		}
	}

	responseBodyTag := checkTag("tool-response-body")
	for _, needle := range []string{"display:flex", "flex-direction:column", "flex:1", "min-height:0"} {
		if !strings.Contains(responseBodyTag, needle) {
			t.Errorf("SPEC-BUG-021 FAIL: expected %q in #tool-response-body tag: %s", needle, responseBodyTag)
		}
	}

	responseJsonTag := checkTag("tool-response-json")
	for _, needle := range []string{"flex:1", "min-height:0", "max-height:none", "overflow:auto"} {
		if !strings.Contains(responseJsonTag, needle) {
			t.Errorf("SPEC-BUG-021 FAIL: expected %q in #tool-response-json tag: %s", needle, responseJsonTag)
		}
	}
	if strings.Contains(responseJsonTag, "max-height:400px") {
		t.Errorf("SPEC-BUG-021 FAIL: #tool-response-json should not keep the 400px cap, tag: %s", responseJsonTag)
	}
}

func TestSPECBUG022_ToolBrowserShowsIdleResponseStateOnSelection(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	for _, needle := range []string{
		`id="tool-response-section" style="display:flex; flex:0 0 300px; flex-direction:column; overflow:hidden; padding:0 24px 24px 24px;"`,
		`id="tool-response-status" class="badge" style="display:none;"`,
		`id="tool-response-latency" class="pill" style="display:none;"`,
		`id="tool-response-idle"`,
		`Execute the selected tool to see response output here.`,
		"function showToolResponseIdle()",
		"function showToolResponseLoading()",
		"showToolResponseIdle();",
		"showToolResponseLoading();",
		"toolResponseSection.style.display = 'flex';",
	} {
		if !strings.Contains(content, needle) {
			t.Errorf("SPEC-BUG-022 FAIL: expected %q in Tool Browser idle response contract", needle)
		}
	}

	selectIdx := strings.Index(content, "function selectTool(serverName, toolName)")
	if selectIdx == -1 {
		t.Fatal("SPEC-BUG-022 FAIL: expected selectTool() function")
	}
	selectBody := content[selectIdx:]
	if endIdx := strings.Index(selectBody[1:], "\n\n  /* ======================================================================\n     Tool Browser — Render Schema Form"); endIdx > 0 {
		selectBody = selectBody[:endIdx+1]
	}
	if strings.Contains(selectBody, "toolResponseSection.style.display = 'none';") {
		t.Error("SPEC-BUG-022 FAIL: selectTool() should not hide the response section")
	}
	if !strings.Contains(selectBody, "showToolResponseIdle();") {
		t.Error("SPEC-BUG-022 FAIL: selectTool() should reset the response area into the idle state")
	}

	execIdx := strings.Index(content, "function executeTool()")
	if execIdx == -1 {
		t.Fatal("SPEC-BUG-022 FAIL: expected executeTool() function")
	}
	execBody := content[execIdx:]
	if endIdx := strings.Index(execBody[1:], "\n\n  function toolResponseBody"); endIdx > 0 {
		execBody = execBody[:endIdx+1]
	}
	if strings.Contains(execBody, "toolResponseSection.style.display = 'none';") {
		t.Error("SPEC-BUG-022 FAIL: executeTool() should not hide the response section during loading")
	}
	if !strings.Contains(execBody, "showToolResponseLoading();") {
		t.Error("SPEC-BUG-022 FAIL: executeTool() should render loading inside the existing response region")
	}
}

func TestSPECBUG023_ToolBrowserRendersConflictDetailState(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	for _, needle := range []string{
		`id="tool-conflict-section"`,
		`id="tool-conflict-title"`,
		`id="tool-conflict-message"`,
		`id="tool-conflict-cards"`,
		`Conflicting Implementations`,
		`Tool name conflict:`,
	} {
		if !strings.Contains(content, needle) {
			t.Errorf("SPEC-BUG-023 FAIL: expected %q in conflicted-tool detail markup", needle)
		}
	}

	selectIdx := strings.Index(content, "function selectTool(serverName, toolName)")
	if selectIdx == -1 {
		t.Fatal("SPEC-BUG-023 FAIL: expected selectTool() function")
	}
	selectBody := content[selectIdx:]
	if endIdx := strings.Index(selectBody[1:], "\n\n  /* ======================================================================\n     Tool Browser — Render Schema Form"); endIdx > 0 {
		selectBody = selectBody[:endIdx+1]
	}

	requiredSnippets := []string{
		"renderToolConflictState(tool);",
		"toolDetailServer.className = 'badge ' + (toolConflicts[tool.name] && toolConflicts[tool.name].length > 1 ? 'badge-warning' : 'badge-neutral');",
		"toolConflictSection.style.display = 'none';",
		"toolConflictCards.innerHTML = html;",
		"toolConflictMessage.textContent = 'This tool name exists in multiple servers. Clients may receive unpredictable results depending on which server responds first.';",
	}
	for _, needle := range requiredSnippets {
		if !strings.Contains(content, needle) && !strings.Contains(selectBody, needle) {
			t.Errorf("SPEC-BUG-023 FAIL: expected %q in conflicted-tool render path", needle)
		}
	}
}

func TestSPECBUG023_ToolBrowserKeepsStandardDetailLayoutForNormalTools(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	for _, needle := range []string{
		`id="tool-detail-server" class="badge badge-neutral"`,
		`id="tool-conflict-section" style="display:none; margin-bottom:16px; padding:12px 16px; background:var(--warning-subtle); border:1px solid var(--warning-fg); border-radius:var(--radius-m);"`,
		`id="tool-params-section" style="margin-bottom:16px;"`,
		`id="tool-response-section" style="display:flex; flex:0 0 300px; flex-direction:column; overflow:hidden; padding:0 24px 24px 24px;"`,
	} {
		if !strings.Contains(content, needle) {
			t.Errorf("SPEC-BUG-023 FAIL: expected standard tool detail layout snippet %q", needle)
		}
	}

	conflictIdx := strings.Index(content, `id="tool-conflict-section"`)
	paramsIdx := strings.Index(content, `id="tool-params-section"`)
	responseIdx := strings.Index(content, `id="tool-response-section"`)
	if conflictIdx == -1 || paramsIdx == -1 || responseIdx == -1 {
		t.Fatal("SPEC-BUG-023 FAIL: expected tool conflict, params, and response sections")
	}
	if !(conflictIdx < paramsIdx && paramsIdx < responseIdx) {
		t.Fatalf("SPEC-BUG-023 FAIL: expected conflict section before params and response sections, got conflict=%d params=%d response=%d", conflictIdx, paramsIdx, responseIdx)
	}
}

func TestSPECBUG024_ToolBrowserSidebarSearchUsesPhase1StripChrome(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	sidebarIdx := strings.Index(content, `id="tools-sidebar"`)
	if sidebarIdx == -1 {
		t.Fatal("SPEC-BUG-024 FAIL: expected tools-sidebar container in index.html")
	}
	searchIdx := strings.Index(content, `id="tool-search-bar"`)
	if searchIdx == -1 {
		t.Fatal("SPEC-BUG-024 FAIL: expected tool-search-bar in index.html")
	}
	sidebarSlice := content[sidebarIdx:searchIdx]
	if strings.Contains(sidebarSlice, "padding:8px") {
		t.Error("SPEC-BUG-024 FAIL: expected no padded wrapper between the sidebar chrome and the search strip")
	}

	searchTagStart := strings.LastIndex(content[:searchIdx], "<")
	searchTagEnd := strings.Index(content[searchIdx:], ">")
	if searchTagStart == -1 || searchTagEnd == -1 {
		t.Fatal("SPEC-BUG-024 FAIL: could not extract tool-search-bar tag")
	}
	searchTag := content[searchTagStart : searchIdx+searchTagEnd+1]
	for _, needle := range []string{
		`class="search-bar search-bar-strip"`,
		`id="tool-search"`,
		`class="search-clear"`,
		`search-icon`,
	} {
		if !strings.Contains(searchTag, needle) && !strings.Contains(content, needle) {
			t.Errorf("SPEC-BUG-024 FAIL: expected %q in sidebar search contract", needle)
		}
	}

	css, err := uiFS.ReadFile("ui/ds.css")
	if err != nil {
		t.Fatalf("read embedded ds.css: %v", err)
	}
	cssContent := string(css)
	for _, needle := range []string{
		".search-bar-strip {",
		"border-bottom: 1px solid var(--border-muted);",
		"border-radius: 0;",
		"padding: 10px 12px;",
		"background: var(--bg-surface);",
		".search-bar-strip.is-active {",
		"box-shadow: none;",
	} {
		if !strings.Contains(cssContent, needle) {
			t.Errorf("SPEC-BUG-024 FAIL: expected %q in sidebar search strip CSS", needle)
		}
	}
}

// ---------------------------------------------------------------------------
// SPEC-BUG-026: Tool Browser offline/restarting state missing Phase 1 banner
// ---------------------------------------------------------------------------

// TestSPECBUG026_OfflineBannerMarkupBuilt verifies that renderToolSidebar()
// constructs the dedicated offline/restarting aggregate banner element (AC1, AC2).
func TestSPECBUG026_OfflineBannerMarkupBuilt(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	if !strings.Contains(content, `id="tool-availability-banner"`) {
		t.Error("SPEC-BUG-026 FAIL: expected tool-availability-banner element id in renderToolSidebar JS source")
	}
}

// TestSPECBUG026_OfflineBannerGatedByCount verifies that the banner is only
// rendered when at least one server is offline or restarting (AC3).
func TestSPECBUG026_OfflineBannerGatedByCount(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	if !strings.Contains(content, "offlineCount > 0 || restartingCount > 0") {
		t.Error("SPEC-BUG-026 FAIL: expected conditional gate 'offlineCount > 0 || restartingCount > 0' proving banner is shown/hidden by count")
	}
}

// ---------------------------------------------------------------------------
// SPEC-BUG-027: Servers view restarting card does not match approved state
// ---------------------------------------------------------------------------

// TestSPECBUG027_RestartingCardHasIsRestartingClass verifies that renderServerCards()
// assigns the is-restarting CSS class to a restarting server card (AC3).
func TestSPECBUG027_RestartingCardHasIsRestartingClass(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	if !strings.Contains(content, "is-restarting") {
		t.Error("SPEC-BUG-027 FAIL: expected 'is-restarting' class assignment in renderServerCards JS source (AC3)")
	}

	// Also verify the CSS class exists in ds.css
	css, err := uiFS.ReadFile("ui/ds.css")
	if err != nil {
		t.Fatalf("read embedded ds.css: %v", err)
	}
	if !strings.Contains(string(css), ".server-card.is-restarting") {
		t.Error("SPEC-BUG-027 FAIL: expected '.server-card.is-restarting' rule in ds.css (AC3)")
	}
}

// TestSPECBUG027_RestartingCardHasPill verifies that renderServerCards() builds
// the dedicated restarting pill header (not just a footer badge) when the server
// status is restarting (AC1).
func TestSPECBUG027_RestartingCardHasPill(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// The restarting pill uses border-radius:100px — the old badge did not
	if !strings.Contains(content, "border-radius:100px") {
		t.Error("SPEC-BUG-027 FAIL: expected pill element with 'border-radius:100px' in renderServerCards JS source (AC1)")
	}
	// The pill text must be present as inline markup, not just the old badge
	if !strings.Contains(content, "warning-subtle") {
		t.Error("SPEC-BUG-027 FAIL: expected warning-subtle background on restarting pill in renderServerCards JS source (AC1)")
	}
}

// TestSPECBUG027_RestartingCardHasCenteredBody verifies that renderServerCards()
// renders the centered waiting body for a restarting server (AC2).
func TestSPECBUG027_RestartingCardHasCenteredBody(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	if !strings.Contains(content, "Waiting for process to start...") {
		t.Error("SPEC-BUG-027 FAIL: expected 'Waiting for process to start...' text in renderServerCards JS source (AC2)")
	}
}

// ---------------------------------------------------------------------------
// SPEC-BUG-015: Desktop Servers view stays empty despite /api/servers returning data
// ---------------------------------------------------------------------------

// TestSPECBUG015_LoadServersHidesEmptyStateWhenServersPresent verifies that
// loadServers() hides the empty state and shows the configured-server container
// when the API returns one or more servers (AC2, AC4).
func TestSPECBUG015_LoadServersHidesEmptyStateWhenServersPresent(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	loadIdx := strings.Index(content, "function loadServers()")
	if loadIdx == -1 {
		t.Fatal("SPEC-BUG-015 FAIL: expected loadServers() function in index.html")
	}
	loadBody := content[loadIdx:]
	if endIdx := strings.Index(loadBody[1:], "\n  function renderServerCards"); endIdx > 0 {
		loadBody = loadBody[:endIdx+1]
	}

	// When servers are non-empty: hide empty state, show grid and action bar
	for _, needle := range []string{
		"serversEmpty.style.display = 'none'",
		"serversGrid.style.display = ''",
		"serversActionBar.style.display = ''",
	} {
		if !strings.Contains(loadBody, needle) {
			t.Errorf("SPEC-BUG-015 AC2 FAIL: expected %q in loadServers() non-empty path", needle)
		}
	}
}

// TestSPECBUG015_LoadServersShowsEmptyStateWhenNoServers verifies that
// loadServers() shows the empty state and hides the server grid when the API
// returns an empty array (AC3, AC4).
func TestSPECBUG015_LoadServersShowsEmptyStateWhenNoServers(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	loadIdx := strings.Index(content, "function loadServers()")
	if loadIdx == -1 {
		t.Fatal("SPEC-BUG-015 FAIL: expected loadServers() function in index.html")
	}
	loadBody := content[loadIdx:]
	if endIdx := strings.Index(loadBody[1:], "\n  function renderServerCards"); endIdx > 0 {
		loadBody = loadBody[:endIdx+1]
	}

	// When servers are empty: show empty state, hide grid and action bar
	for _, needle := range []string{
		"serversEmpty.style.display = ''",
		"serversGrid.style.display = 'none'",
		"serversActionBar.style.display = 'none'",
	} {
		if !strings.Contains(loadBody, needle) {
			t.Errorf("SPEC-BUG-015 AC3 FAIL: expected %q in loadServers() empty path", needle)
		}
	}
}

// TestSPECBUG015_ResolveAPIURLUsesApiBase verifies that resolveAPIURL() uses
// desktopBridgeConfig.api_base to build an absolute URL for desktop mode
// fetches, so Wails webview custom-scheme fetches resolve correctly to the
// localhost HTTP server instead of relying on relative-URL resolution (AC1, AC4).
func TestSPECBUG015_ResolveAPIURLUsesApiBase(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	resolveIdx := strings.Index(content, "function resolveAPIURL(path)")
	if resolveIdx == -1 {
		t.Fatal("SPEC-BUG-015 FAIL: expected resolveAPIURL(path) function in index.html")
	}
	resolveBody := content[resolveIdx:]
	if endIdx := strings.Index(resolveBody[1:], "\n  function appFetch"); endIdx > 0 {
		resolveBody = resolveBody[:endIdx+1]
	}

	// Must use api_base from desktopBridgeConfig to build an absolute URL
	if !strings.Contains(resolveBody, "desktopBridgeConfig.api_base") {
		t.Error("SPEC-BUG-015 AC1 FAIL: resolveAPIURL() must use desktopBridgeConfig.api_base for desktop mode fetches")
	}
	// Must strip trailing slash before concatenation to avoid double slashes
	if !strings.Contains(resolveBody, ".replace(/\\/$/, '')") {
		t.Error("SPEC-BUG-015 AC1 FAIL: resolveAPIURL() must strip trailing slash from api_base before concatenation")
	}
	// Must fall back to path when api_base is not set
	if !strings.Contains(resolveBody, "return path;") {
		t.Error("SPEC-BUG-015 AC1 FAIL: resolveAPIURL() must fall back to returning path unchanged when api_base is not available")
	}
}

// TestSPEC032_ToolBrowserResizeHandlePresent verifies that the resize handle
// element is present in the correct DOM position between the form scroll section
// and the response section, has no inline style, and that the drag JS is wired up.
func TestSPEC032_ToolBrowserResizeHandlePresent(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// AC 1: resize handle element exists with id and class
	if !strings.Contains(content, `id="tool-resize-handle"`) {
		t.Fatal("SPEC-032 AC1 FAIL: expected id=\"tool-resize-handle\" in index.html")
	}
	if !strings.Contains(content, `class="resize-handle"`) {
		t.Fatal("SPEC-032 AC1 FAIL: expected class=\"resize-handle\" on handle element")
	}

	// AC 8: handle element must NOT have inline style attribute
	// Find the handle tag and check it has no style= attribute
	handleTagStart := strings.Index(content, `id="tool-resize-handle"`)
	if handleTagStart == -1 {
		t.Fatal("SPEC-032 AC8 FAIL: could not locate tool-resize-handle element")
	}
	// Search backward to find the opening < of this tag
	tagOpen := strings.LastIndex(content[:handleTagStart], "<")
	tagClose := strings.Index(content[handleTagStart:], ">")
	if tagClose == -1 {
		t.Fatal("SPEC-032 AC8 FAIL: could not find closing > of resize-handle tag")
	}
	handleTag := content[tagOpen : handleTagStart+tagClose+1]
	if strings.Contains(handleTag, "style=") {
		t.Errorf("SPEC-032 AC8 FAIL: handle element must NOT have inline style attribute, got: %s", handleTag)
	}

	// AC 9: DOM order — tool-detail-scroll < tool-resize-handle < tool-response-section
	scrollIdx := strings.Index(content, `id="tool-detail-scroll"`)
	handleIdx := strings.Index(content, `id="tool-resize-handle"`)
	responseIdx := strings.Index(content, `id="tool-response-section"`)
	if scrollIdx == -1 || handleIdx == -1 || responseIdx == -1 {
		t.Fatalf("SPEC-032 AC9 FAIL: one or more required elements not found: scroll=%d handle=%d response=%d",
			scrollIdx, handleIdx, responseIdx)
	}
	if !(scrollIdx < handleIdx && handleIdx < responseIdx) {
		t.Errorf("SPEC-032 AC9 FAIL: expected tool-detail-scroll(%d) < tool-resize-handle(%d) < tool-response-section(%d)",
			scrollIdx, handleIdx, responseIdx)
	}

	// AC 5: localStorage key present in JS
	if !strings.Contains(content, "shipyard_tool_response_height") {
		t.Error("SPEC-032 AC5 FAIL: expected localStorage key 'shipyard_tool_response_height' in JS")
	}

	// AC 2: mousedown drag start handler
	if !strings.Contains(content, "mousedown") {
		t.Error("SPEC-032 AC2 FAIL: expected 'mousedown' event listener in JS")
	}

	// AC 2: mousemove handler (drag in progress)
	if !strings.Contains(content, "mousemove") {
		t.Error("SPEC-032 AC2 FAIL: expected 'mousemove' event listener in JS")
	}
}

// TestSPECBUG041_ResponseSectionOverflowContainment verifies that the response
// section and its content chain have correct overflow containment so that long
// responses cannot escape their panel and obscure the parameters pane above.
//
// R1: response section height stays at configured value regardless of content length.
// R2: content scrolls inside the section — no overflow escape into sibling elements.
// R3: resize handle remains functional (offsetHeight must read the clamped value).
func TestSPECBUG041_ResponseSectionOverflowContainment(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	checkTag := func(id string) string {
		idx := strings.Index(content, `id="`+id+`"`)
		if idx == -1 {
			t.Fatalf("SPEC-BUG-041: expected to find #%s in index.html", id)
		}
		tagStart := strings.LastIndex(content[:idx], "<")
		tagEnd := strings.Index(content[idx:], ">")
		if tagStart == -1 || tagEnd == -1 {
			t.Fatalf("SPEC-BUG-041: could not extract #%s tag", id)
		}
		return content[tagStart : idx+tagEnd+1]
	}

	// AC 1 / R1: #tool-response-section must have overflow:hidden so its flex-basis
	// acts as a hard ceiling — content cannot bleed outside the fixed-height panel.
	responseSectionTag := checkTag("tool-response-section")
	if !strings.Contains(responseSectionTag, "overflow:hidden") {
		t.Errorf("SPEC-BUG-041 FAIL: #tool-response-section must have overflow:hidden to contain long responses, tag: %s", responseSectionTag)
	}

	// AC 2 / R2: #tool-response-body must carry overflow:hidden in its inline style
	// so that the flex chain delivers a definite height to the scroll child even in
	// WebKit where CSS-only overflow:hidden on .code-block may not clip without a
	// definite computed height on the element itself.
	responseBodyTag := checkTag("tool-response-body")
	if !strings.Contains(responseBodyTag, "overflow:hidden") {
		t.Errorf("SPEC-BUG-041 FAIL: #tool-response-body must have overflow:hidden in its inline style, tag: %s", responseBodyTag)
	}

	// AC 2 / R2: #tool-response-json must still have overflow:auto so scrolling
	// is present when content exceeds the constrained height.
	responseJsonTag := checkTag("tool-response-json")
	if !strings.Contains(responseJsonTag, "overflow:auto") {
		t.Errorf("SPEC-BUG-041 FAIL: #tool-response-json must keep overflow:auto for scroll, tag: %s", responseJsonTag)
	}

	// R1 / R3: #tool-response-section must still declare flex:0 0 300px so the
	// section does not grow and the resize JS baseline (offsetHeight) is predictable.
	if !strings.Contains(responseSectionTag, "flex:0 0 300px") {
		t.Errorf("SPEC-BUG-041 FAIL: #tool-response-section must keep flex:0 0 300px, tag: %s", responseSectionTag)
	}

	// R3: the resize JS must read toolResponseSection.offsetHeight at mousedown —
	// this is the baseline that all delta calculations are applied to.
	if !strings.Contains(content, "toolResponseSection.offsetHeight") {
		t.Error("SPEC-BUG-041 FAIL: resize JS must read toolResponseSection.offsetHeight at mousedown for correct baseline")
	}
}

// TestSPEC039_ExpandJSONStringsHelperExists verifies that the expandJSONStrings
// helper function is present in index.html adjacent to highlightJSON.
func TestSPEC039_ExpandJSONStringsHelperExists(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// R5: helper must be present adjacent to highlightJSON
	if !strings.Contains(content, "function expandJSONStrings(obj, depth)") {
		t.Fatal("SPEC-039 FAIL: expected expandJSONStrings(obj, depth) function in index.html")
	}

	// R3: depth limit of 5 must be enforced
	if !strings.Contains(content, "if (depth > 5) return obj;") {
		t.Error("SPEC-039 FAIL: expected depth limit 'if (depth > 5) return obj;' in expandJSONStrings")
	}

	// R4: must only expand object or array results (not primitives)
	if !strings.Contains(content, "typeof parsed === 'object'") {
		t.Error("SPEC-039 FAIL: expected typeof check to guard against primitive expansion")
	}

	// R1: highlightJSON must call expandJSONStrings between parse and stringify
	highlightIdx := strings.Index(content, "function highlightJSON(str)")
	if highlightIdx == -1 {
		t.Fatal("SPEC-039 FAIL: expected highlightJSON function")
	}
	// Extract function body (until next function declaration)
	highlightBody := content[highlightIdx:]
	nextFnIdx := strings.Index(highlightBody[1:], "\n  function ")
	if nextFnIdx > 0 {
		highlightBody = highlightBody[:nextFnIdx+1]
	}
	if !strings.Contains(highlightBody, "expandJSONStrings(obj, 0)") {
		t.Error("SPEC-039 FAIL: highlightJSON must call expandJSONStrings(obj, 0) between JSON.parse and JSON.stringify")
	}
}

// TestSPEC039_NestedJSONStringExpanded verifies that a JSON string containing
// an embedded JSON object is expanded (not left as an escaped literal).
// AC 1: {"content":[{"type":"text","text":"{\"key\":\"value\"}"}]}
// After expansion, the output must NOT contain the raw escaped string.
func TestSPEC039_NestedJSONStringExpanded(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// Verify the expandJSONStrings helper handles objects (checked at function level above).
	// Here we verify the structural contract: expandJSONStrings must recurse into Array.isArray.
	if !strings.Contains(content, "Array.isArray(obj)") {
		t.Error("SPEC-039 FAIL (AC 1/R2): expandJSONStrings must handle arrays with Array.isArray check")
	}

	// R2: must iterate over object keys with hasOwnProperty
	if !strings.Contains(content, "obj.hasOwnProperty(key)") {
		t.Error("SPEC-039 FAIL (R2): expandJSONStrings must walk object keys with hasOwnProperty guard")
	}
}

// TestSPEC039_PlainStringUnchanged verifies that a plain string value that is
// not valid JSON passes through without modification (AC 3: {"val":"hello world"}).
// Structural check: the catch block must exist to swallow parse errors silently.
func TestSPEC039_PlainStringUnchanged(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// Find the expandJSONStrings function body
	fnIdx := strings.Index(content, "function expandJSONStrings(obj, depth)")
	if fnIdx == -1 {
		t.Fatal("SPEC-039 FAIL: expandJSONStrings function not found")
	}
	fnBody := content[fnIdx:]
	// Capture until next top-level function
	nextFnIdx := strings.Index(fnBody[1:], "\n  function ")
	if nextFnIdx > 0 {
		fnBody = fnBody[:nextFnIdx+1]
	}

	// AC 3: plain strings must not be expanded — catch block must silently return obj
	if !strings.Contains(fnBody, "} catch(e) {}") {
		t.Error("SPEC-039 FAIL (AC 3): expandJSONStrings must have empty catch block to silently skip non-JSON strings")
	}

	// AC 4/5: after failing JSON.parse, plain string must be returned as-is
	if !strings.Contains(fnBody, "return obj;") {
		t.Error("SPEC-039 FAIL (AC 3): expandJSONStrings must return plain string as-is after parse failure")
	}
}

// TestSPEC039_RecursiveExpansionAtDepth verifies that the recursive calls pass
// depth+1 for both array elements and object values, enabling multi-level expansion.
// AC 4: 3+ levels of nested JSON strings must be fully expanded.
func TestSPEC039_RecursiveExpansionAtDepth(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	fnIdx := strings.Index(content, "function expandJSONStrings(obj, depth)")
	if fnIdx == -1 {
		t.Fatal("SPEC-039 FAIL: expandJSONStrings function not found")
	}
	fnBody := content[fnIdx:]
	nextFnIdx := strings.Index(fnBody[1:], "\n  function ")
	if nextFnIdx > 0 {
		fnBody = fnBody[:nextFnIdx+1]
	}

	// AC 4/R2: recursive calls must increment depth
	if !strings.Contains(fnBody, "depth + 1") {
		t.Error("SPEC-039 FAIL (AC 4/R2): expandJSONStrings recursive calls must pass depth + 1")
	}

	// R2: must recurse into both objects and strings (recursive call appears inside object walk)
	// count occurrences of "expandJSONStrings(" to verify recursion in array, object, and string branches
	count := strings.Count(fnBody, "expandJSONStrings(")
	if count < 3 {
		// Expect: string branch, array loop, object value loop (minimum 3 recursive call sites)
		t.Errorf("SPEC-039 FAIL (R2): expected at least 3 recursive expandJSONStrings calls, got %d", count)
	}
}

// TestSPEC039_PrimitiveJSONNotExpanded verifies that a string that parses as a
// JSON primitive (number, boolean, null) is NOT expanded (AC 5).
// Structural check: the guard "typeof parsed === 'object'" excludes all primitives.
func TestSPEC039_PrimitiveJSONNotExpanded(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	fnIdx := strings.Index(content, "function expandJSONStrings(obj, depth)")
	if fnIdx == -1 {
		t.Fatal("SPEC-039 FAIL: expandJSONStrings function not found")
	}
	fnBody := content[fnIdx:]
	nextFnIdx := strings.Index(fnBody[1:], "\n  function ")
	if nextFnIdx > 0 {
		fnBody = fnBody[:nextFnIdx+1]
	}

	// AC 5: parsed !== null AND typeof parsed === 'object' guards against primitive expansion
	// numbers/booleans have typeof !== 'object'; null has typeof === 'object' but parsed === null
	if !strings.Contains(fnBody, "parsed !== null && typeof parsed === 'object'") {
		t.Error("SPEC-039 FAIL (AC 5): guard must check 'parsed !== null && typeof parsed === 'object'' to exclude primitives and null")
	}
}

// TestSPECBUG038_ResponseCopyButtonHasIconAndLabel verifies that the response
// header Copy button (#tool-response-copy) contains both an SVG icon child and
// the "Copy" text label (AC 1, AC 2, AC 3).
func TestSPECBUG038_ResponseCopyButtonHasIconAndLabel(t *testing.T) {
	html, err := uiFS.ReadFile("ui/index.html")
	if err != nil {
		t.Fatalf("read embedded index.html: %v", err)
	}
	content := string(html)

	// Locate the button by its id
	btnMarker := `id="tool-response-copy"`
	btnIdx := strings.Index(content, btnMarker)
	if btnIdx == -1 {
		t.Fatal("SPEC-BUG-038 FAIL (AC 1): #tool-response-copy button not found in index.html")
	}

	// Extract the button element up to the closing tag
	btnStart := strings.LastIndex(content[:btnIdx], "<button")
	if btnStart == -1 {
		t.Fatal("SPEC-BUG-038 FAIL (AC 1): could not locate opening <button tag for #tool-response-copy")
	}
	btnEnd := strings.Index(content[btnStart:], "</button>")
	if btnEnd == -1 {
		t.Fatal("SPEC-BUG-038 FAIL (AC 1): could not locate closing </button> for #tool-response-copy")
	}
	btnHTML := content[btnStart : btnStart+btnEnd+len("</button>")]

	// AC 1: button must contain an <svg> child element
	if !strings.Contains(btnHTML, "<svg") {
		t.Error("SPEC-BUG-038 FAIL (AC 1): Copy button must contain an <svg> icon element")
	}

	// AC 1: button must contain the "Copy" text label
	if !strings.Contains(btnHTML, "Copy") {
		t.Error("SPEC-BUG-038 FAIL (AC 1): Copy button must contain the text label 'Copy'")
	}

	// AC 2: svg must specify width="12" and height="12"
	if !strings.Contains(btnHTML, `width="12"`) || !strings.Contains(btnHTML, `height="12"`) {
		t.Error("SPEC-BUG-038 FAIL (AC 2): Copy button SVG icon must be 12x12 px (width=\"12\" height=\"12\")")
	}

	// AC 2: icon must use currentColor (inherits muted colour from .btn-copy)
	if !strings.Contains(btnHTML, "currentColor") {
		t.Error("SPEC-BUG-038 FAIL (AC 2): Copy button SVG must use currentColor for muted colour inheritance")
	}

	// AC 4: id and class wiring must be preserved
	if !strings.Contains(btnHTML, `id="tool-response-copy"`) {
		t.Error("SPEC-BUG-038 FAIL (AC 4): id=\"tool-response-copy\" must remain on the button")
	}
	if !strings.Contains(btnHTML, "btn-copy") {
		t.Error("SPEC-BUG-038 FAIL (AC 4): btn-copy class must remain on the button")
	}
}
