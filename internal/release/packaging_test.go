package release

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func repoRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
}

func readRepoFile(t *testing.T, rel string) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(repoRoot(t), rel))
	if err != nil {
		t.Fatalf("read %s: %v", rel, err)
	}
	return string(data)
}

func TestSPECBUG130_WailsV3PackagingTasks(t *testing.T) {
	taskfile := readRepoFile(t, "Taskfile.yml")
	for _, needle := range []string{
		"darwin:package:",
		"scripts/package-macos-app.sh --skip-build",
		"darwin:sign:",
		"scripts/sign-macos-app.sh",
		"darwin:sign:notarize:",
		"scripts/sign-macos-app.sh --notarize",
	} {
		if !strings.Contains(taskfile, needle) {
			t.Errorf("SPEC-BUG-130 FAIL: Taskfile.yml missing %q", needle)
		}
	}

	makefile := readRepoFile(t, "Makefile")
	for _, needle := range []string{
		"package-macos:",
		"wails3 task darwin:package",
		"sign-macos:",
		"wails3 sign GOOS=darwin",
		"notarize-macos:",
		"wails3 task darwin:sign:notarize",
	} {
		if !strings.Contains(makefile, needle) {
			t.Errorf("SPEC-BUG-130 FAIL: Makefile missing %q", needle)
		}
	}
}

func TestSPECBUG130_SigningPrerequisitesFailClearly(t *testing.T) {
	signScript := readRepoFile(t, "scripts/sign-macos-app.sh")
	for _, needle := range []string{
		"missing macOS signing identity",
		"SHIPYARD_MACOS_SIGN_IDENTITY",
		"SIGN_IDENTITY",
		"security find-identity -v -p codesigning",
		"missing notarization keychain profile",
		"SHIPYARD_MACOS_NOTARY_PROFILE",
		"KEYCHAIN_PROFILE",
		"xcrun notarytool",
	} {
		if !strings.Contains(signScript, needle) {
			t.Errorf("SPEC-BUG-130 FAIL: signing script missing %q", needle)
		}
	}
}

func TestSPECBUG130_ReleaseDocsDescribeArtifactAndRawBuild(t *testing.T) {
	readme := readRepoFile(t, "README.md")
	for _, needle := range []string{
		"make package-macos",
		"`bin/Shipyard.app`",
		"unsigned `.app` bundle",
		"make sign-macos",
		"make notarize-macos",
		"make wails-build",
		"GoReleaser",
		"cross-platform headless CLI binaries",
	} {
		if !strings.Contains(readme, needle) {
			t.Errorf("SPEC-BUG-130 FAIL: README.md missing %q", needle)
		}
	}
}

func TestSPECBUG130_DesktopWorkflowUsesWailsV3PackagePath(t *testing.T) {
	workflow := readRepoFile(t, ".github/workflows/desktop.yml")
	if strings.Contains(workflow, "github.com/wailsapp/wails/v2") || strings.Contains(workflow, "wails build") {
		t.Fatal("SPEC-BUG-130 FAIL: desktop workflow must not use Wails v2 build commands")
	}
	for _, needle := range []string{
		"github.com/wailsapp/wails/v3/cmd/wails3@v3.0.0-alpha2.117",
		"wails3 task build",
		"wails3 task darwin:package",
		"bin/Shipyard.app",
		"bin/shipyard-macos.zip",
	} {
		if !strings.Contains(workflow, needle) {
			t.Errorf("SPEC-BUG-130 FAIL: desktop workflow missing %q", needle)
		}
	}
}
