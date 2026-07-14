package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/sloik/shipyard/internal/web"
	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"
)

// desktopApp holds lifecycle state for the Wails desktop windows.
type desktopApp struct {
	port       int
	cancelFunc context.CancelFunc
	layoutPath string

	mu           sync.Mutex
	app          *application.App
	mainWindow   application.Window
	panelWindows map[string]application.Window
	layout       desktopWindowLayout
	quitting     bool
}

type desktopWindowBounds struct {
	X      int `json:"x"`
	Y      int `json:"y"`
	Width  int `json:"width"`
	Height int `json:"height"`
}

type desktopPanelLayout struct {
	Detached bool                `json:"detached"`
	Bounds   desktopWindowBounds `json:"bounds"`
}

type desktopWindowLayout struct {
	Main   desktopWindowBounds           `json:"main"`
	Panels map[string]desktopPanelLayout `json:"panels"`
}

type desktopConfig struct {
	APIBase       string `json:"api_base"`
	NativeWindows bool   `json:"native_windows"`
	WSBase        string `json:"ws_base"`
}

var detachablePanels = map[string]string{
	"timeline": "Traffic",
	"tools":    "Tools",
	"history":  "History",
	"servers":  "Servers",
}

func desktopSingleInstanceOptions(desktop *desktopApp) *application.SingleInstanceOptions {
	return &application.SingleInstanceOptions{
		UniqueID: "com.sloik.shipyard.local",
		ExitCode: 0,
		OnSecondInstanceLaunch: func(data application.SecondInstanceData) {
			if desktop != nil {
				desktop.showDashboard()
			}
		},
	}
}

// runDesktop starts the Wails v3 native shell using Shipyard's bundled
// frontend. It blocks until the app quits. The existing localhost HTTP server
// remains the source of truth for API, websocket, and MCP proxy behavior.
var runDesktopFn = runDesktop

func runDesktop(port int, cancel context.CancelFunc) {
	desktop := &desktopApp{
		port:         port,
		cancelFunc:   cancel,
		layoutPath:   desktopLayoutPath(),
		panelWindows: make(map[string]application.Window),
		layout:       defaultDesktopWindowLayout(),
	}

	if !waitForServer(port, 10*time.Second) {
		slog.Error("HTTP server did not become ready in time", "port", port)
		cancel()
		return
	}

	slog.Info("opening desktop window", "bridge_port", port)

	uiAssets, err := web.UIAssets()
	if err != nil {
		slog.Error("failed to load embedded desktop UI", "error", err)
		cancel()
		return
	}

	if layout, err := loadDesktopWindowLayout(desktop.layoutPath); err == nil {
		desktop.layout = layout
	} else if !os.IsNotExist(err) {
		slog.Warn("failed to load desktop window layout", "path", desktop.layoutPath, "error", err)
	}

	wailsApp := application.New(application.Options{
		Name:           "Shipyard",
		Description:    "MCP traffic inspector and tool browser",
		SingleInstance: desktopSingleInstanceOptions(desktop),
		Assets: application.AssetOptions{
			Handler:        newDesktopBridgeWithAssets(port, application.AssetFileServerFS(uiAssets), desktop),
			DisableLogging: true,
		},
		Mac: application.MacOptions{
			ApplicationShouldTerminateAfterLastWindowClosed: false,
		},
		OnShutdown: desktop.shutdown,
		ShouldQuit: desktop.shouldQuit,
	})
	desktop.app = wailsApp

	desktop.mainWindow = wailsApp.Window.NewWithOptions(desktop.windowOptions("main", "Shipyard", "/", desktop.layout.Main))
	desktop.registerMainWindowHooks()
	desktop.configureTray()
	desktop.restoreDetachedWindows()

	if err := wailsApp.Run(); err != nil {
		slog.Error("wails error", "error", err)
	}

	cancel()
}

func (a *desktopApp) windowOptions(name, title, route string, bounds desktopWindowBounds) application.WebviewWindowOptions {
	bounds = normalizeWindowBounds(bounds, defaultWindowBounds(name))
	opts := application.WebviewWindowOptions{
		Name:             name,
		Title:            title,
		Width:            bounds.Width,
		Height:           bounds.Height,
		MinWidth:         900,
		MinHeight:        600,
		URL:              route,
		BackgroundColour: application.NewRGBA(26, 26, 46, 255),
	}
	if bounds.X != 0 || bounds.Y != 0 {
		opts.InitialPosition = application.WindowXY
		opts.X = bounds.X
		opts.Y = bounds.Y
	}
	return opts
}

func (a *desktopApp) registerMainWindowHooks() {
	if a.mainWindow == nil {
		return
	}
	a.mainWindow.RegisterHook(events.Common.WindowClosing, func(e *application.WindowEvent) {
		a.mu.Lock()
		quitting := a.quitting
		a.mu.Unlock()
		a.recordMainBounds()
		if quitting {
			return
		}
		a.mainWindow.Hide()
		e.Cancel()
	})
	a.mainWindow.OnWindowEvent(events.Common.WindowDidMove, func(e *application.WindowEvent) {
		a.recordMainBounds()
	})
	a.mainWindow.OnWindowEvent(events.Common.WindowDidResize, func(e *application.WindowEvent) {
		a.recordMainBounds()
	})
}

func (a *desktopApp) configureTray() {
	if a.app == nil || a.mainWindow == nil {
		return
	}
	tray := a.app.SystemTray.New()
	icon := shipyardTrayIcon()
	if runtime.GOOS == "darwin" {
		tray.SetTemplateIcon(icon)
	} else {
		tray.SetIcon(icon)
	}
	tray.SetTooltip("Shipyard")

	menu := a.app.NewMenu()
	menu.Add("Show Dashboard").OnClick(func(ctx *application.Context) {
		a.showDashboard()
	})
	menu.AddSeparator()
	menu.Add("Quit").OnClick(func(ctx *application.Context) {
		a.requestQuit()
	})
	tray.SetMenu(menu)
	tray.OnClick(func() {
		a.toggleDashboard()
	})
	tray.OnRightClick(func() {
		tray.OpenMenu()
	})
}

func (a *desktopApp) showDashboard() {
	if a.mainWindow == nil {
		return
	}
	a.mainWindow.Show()
	a.mainWindow.Focus()
}

func (a *desktopApp) toggleDashboard() {
	if a.mainWindow == nil {
		return
	}
	if a.mainWindow.IsVisible() {
		a.recordMainBounds()
		a.mainWindow.Hide()
		return
	}
	a.showDashboard()
}

func (a *desktopApp) OpenPanelWindow(panel string) error {
	title, ok := detachablePanels[panel]
	if !ok {
		return fmt.Errorf("unknown panel %q", panel)
	}
	if a.app == nil {
		return fmt.Errorf("desktop app is not ready")
	}

	a.mu.Lock()
	if existing := a.panelWindows[panel]; existing != nil {
		a.mu.Unlock()
		existing.Show()
		existing.Focus()
		return nil
	}
	panelLayout := a.layout.Panels[panel]
	a.mu.Unlock()

	win := a.app.Window.NewWithOptions(a.windowOptions("panel-"+panel, title+" - Shipyard", "/#"+panel, panelLayout.Bounds))
	a.mu.Lock()
	a.panelWindows[panel] = win
	a.layout.Panels[panel] = desktopPanelLayout{
		Detached: true,
		Bounds:   normalizeWindowBounds(panelLayout.Bounds, defaultWindowBounds("panel-"+panel)),
	}
	a.mu.Unlock()
	a.saveLayout()

	win.RegisterHook(events.Common.WindowClosing, func(e *application.WindowEvent) {
		a.recordPanelBounds(panel, win, false)
		a.mu.Lock()
		delete(a.panelWindows, panel)
		a.mu.Unlock()
	})
	win.OnWindowEvent(events.Common.WindowDidMove, func(e *application.WindowEvent) {
		a.recordPanelBounds(panel, win, true)
	})
	win.OnWindowEvent(events.Common.WindowDidResize, func(e *application.WindowEvent) {
		a.recordPanelBounds(panel, win, true)
	})

	return nil
}

func (a *desktopApp) restoreDetachedWindows() {
	for panel, panelLayout := range a.layout.Panels {
		if panelLayout.Detached {
			if err := a.OpenPanelWindow(panel); err != nil {
				slog.Warn("failed to restore detached desktop panel", "panel", panel, "error", err)
			}
		}
	}
}

func (a *desktopApp) recordMainBounds() {
	if a.mainWindow == nil {
		return
	}
	a.mu.Lock()
	a.layout.Main = windowBounds(a.mainWindow, a.layout.Main)
	a.mu.Unlock()
	a.saveLayout()
}

func (a *desktopApp) recordPanelBounds(panel string, win application.Window, detached bool) {
	a.mu.Lock()
	current := a.layout.Panels[panel]
	current.Detached = detached
	current.Bounds = windowBounds(win, current.Bounds)
	a.layout.Panels[panel] = current
	a.mu.Unlock()
	a.saveLayout()
}

func (a *desktopApp) saveAllWindowLayouts() {
	a.recordMainBounds()
	a.mu.Lock()
	for panel, win := range a.panelWindows {
		current := a.layout.Panels[panel]
		current.Detached = true
		current.Bounds = windowBounds(win, current.Bounds)
		a.layout.Panels[panel] = current
	}
	a.mu.Unlock()
	a.saveLayout()
}

func (a *desktopApp) saveLayout() {
	a.mu.Lock()
	layout := cloneDesktopWindowLayout(a.layout)
	path := a.layoutPath
	a.mu.Unlock()
	if path == "" {
		return
	}
	if err := saveDesktopWindowLayout(path, layout); err != nil {
		slog.Warn("failed to save desktop window layout", "path", path, "error", err)
	}
}

func (a *desktopApp) shouldQuit() bool {
	a.mu.Lock()
	a.quitting = true
	a.mu.Unlock()
	a.saveAllWindowLayouts()
	if a.cancelFunc != nil {
		a.cancelFunc()
	}
	return true
}

func (a *desktopApp) requestQuit() {
	a.shouldQuit()
	if a.app != nil {
		a.app.Quit()
	}
}

func (a *desktopApp) shutdown() {
	slog.Info("desktop app shutdown complete")
	a.shouldQuit()
}

// waitForServer polls the HTTP server until it responds or timeout is reached.
func waitForServer(port int, timeout time.Duration) bool {
	url := fmt.Sprintf("http://localhost:%d/api/servers", port)
	deadline := time.Now().Add(timeout)
	client := &http.Client{Timeout: 500 * time.Millisecond}

	for time.Now().Before(deadline) {
		resp, err := client.Get(url)
		if err == nil {
			resp.Body.Close()
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	return false
}

type desktopNativeController interface {
	OpenPanelWindow(panel string) error
}

type desktopBridge struct {
	config []byte
	proxy  *httputil.ReverseProxy
	assets http.Handler
	native desktopNativeController
}

func newDesktopBridge(port int) http.Handler {
	return newDesktopBridgeWithAssets(port, http.NotFoundHandler(), nil)
}

func newDesktopBridgeWithAssets(port int, assets http.Handler, native desktopNativeController) http.Handler {
	target, err := url.Parse(fmt.Sprintf("http://127.0.0.1:%d", port))
	if err != nil {
		panic(fmt.Sprintf("invalid desktop bridge target: %v", err))
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, proxyErr error) {
		slog.Error("desktop bridge proxy error", "path", r.URL.Path, "error", proxyErr)
		http.Error(w, "desktop bridge proxy error", http.StatusBadGateway)
	}

	config, err := json.Marshal(desktopConfig{
		APIBase:       fmt.Sprintf("http://127.0.0.1:%d", port),
		NativeWindows: native != nil,
		WSBase:        fmt.Sprintf("ws://127.0.0.1:%d", port),
	})
	if err != nil {
		panic(fmt.Sprintf("marshal desktop bridge config: %v", err))
	}

	return &desktopBridge{
		config: config,
		proxy:  proxy,
		assets: assets,
		native: native,
	}
}

func (h *desktopBridge) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	slog.Debug("desktop bridge request", "method", r.Method, "path", r.URL.Path)

	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/_shipyard/desktop-config":
		w.Header().Set("Content-Type", "application/json")
		w.Write(h.config)
	case r.Method == http.MethodPost && r.URL.Path == "/_shipyard/windows/open":
		h.openPanelWindow(w, r)
	case strings.HasPrefix(r.URL.Path, "/_shipyard/"):
		http.NotFound(w, r)
	case strings.HasPrefix(r.URL.Path, "/api/") || r.URL.Path == "/ws":
		h.proxy.ServeHTTP(w, r)
	default:
		h.assets.ServeHTTP(w, r)
	}
}

func (h *desktopBridge) openPanelWindow(w http.ResponseWriter, r *http.Request) {
	if h.native == nil {
		http.Error(w, "native windows unavailable", http.StatusNotImplemented)
		return
	}
	panel := r.URL.Query().Get("panel")
	if _, ok := detachablePanels[panel]; !ok {
		http.Error(w, "unknown panel", http.StatusBadRequest)
		return
	}
	if err := h.native.OpenPanelWindow(panel); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func defaultDesktopWindowLayout() desktopWindowLayout {
	return desktopWindowLayout{
		Main:   defaultWindowBounds("main"),
		Panels: make(map[string]desktopPanelLayout),
	}
}

func defaultWindowBounds(name string) desktopWindowBounds {
	if strings.HasPrefix(name, "panel-") {
		return desktopWindowBounds{Width: 1100, Height: 720}
	}
	return desktopWindowBounds{Width: 1280, Height: 800}
}

func normalizeWindowBounds(bounds desktopWindowBounds, fallback desktopWindowBounds) desktopWindowBounds {
	if bounds.Width <= 0 {
		bounds.Width = fallback.Width
	}
	if bounds.Height <= 0 {
		bounds.Height = fallback.Height
	}
	return bounds
}

func windowBounds(win application.Window, fallback desktopWindowBounds) desktopWindowBounds {
	if win == nil {
		return fallback
	}
	bounds := win.Bounds()
	result := desktopWindowBounds{
		X:      bounds.X,
		Y:      bounds.Y,
		Width:  bounds.Width,
		Height: bounds.Height,
	}
	return normalizeWindowBounds(result, fallback)
}

func desktopLayoutPath() string {
	return filepath.Join(dataDirFn(), "window-layout.json")
}

func loadDesktopWindowLayout(path string) (desktopWindowLayout, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return desktopWindowLayout{}, err
	}
	var layout desktopWindowLayout
	if err := json.Unmarshal(data, &layout); err != nil {
		return desktopWindowLayout{}, err
	}
	if layout.Panels == nil {
		layout.Panels = make(map[string]desktopPanelLayout)
	}
	layout.Main = normalizeWindowBounds(layout.Main, defaultWindowBounds("main"))
	return layout, nil
}

func saveDesktopWindowLayout(path string, layout desktopWindowLayout) error {
	if layout.Panels == nil {
		layout.Panels = make(map[string]desktopPanelLayout)
	}
	layout.Main = normalizeWindowBounds(layout.Main, defaultWindowBounds("main"))
	data, err := json.MarshalIndent(layout, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, append(data, '\n'), 0o600)
}

func cloneDesktopWindowLayout(layout desktopWindowLayout) desktopWindowLayout {
	clone := desktopWindowLayout{
		Main:   layout.Main,
		Panels: make(map[string]desktopPanelLayout, len(layout.Panels)),
	}
	for panel, panelLayout := range layout.Panels {
		clone.Panels[panel] = panelLayout
	}
	return clone
}

func shipyardTrayIcon() []byte {
	img := image.NewRGBA(image.Rect(0, 0, 18, 18))
	ink := color.RGBA{A: 255}
	for y := 3; y <= 14; y++ {
		for x := 8; x <= 9; x++ {
			img.Set(x, y, ink)
		}
	}
	for x := 4; x <= 13; x++ {
		img.Set(x, 11, ink)
	}
	for x := 5; x <= 12; x++ {
		img.Set(x, 12, ink)
	}
	for x := 7; x <= 10; x++ {
		img.Set(x, 4, ink)
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		return nil
	}
	return buf.Bytes()
}
