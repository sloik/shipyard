//go:build windows

package capture

// freeDiskBytes is unavailable on Windows; callers treat ok=false as unknown.
func freeDiskBytes(dir string) (uint64, bool) { return 0, false }
