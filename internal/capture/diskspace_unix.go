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
	// Field types differ by platform (Bsize is int64 on Linux, Bavail is int64
	// on FreeBSD); blocksToBytes clamps and saturates instead of wrapping.
	return blocksToBytes(st.Bavail, st.Bsize), true
}
