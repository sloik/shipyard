//go:build !windows

package capture

import "syscall"

// freeDiskBytes returns the bytes available to unprivileged users on the
// filesystem containing dir.
func freeDiskBytes(dir string) (uint64, bool) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(dir, &st); err != nil {
		return 0, false
	}
	return uint64(st.Bavail) * uint64(st.Bsize), true
}
