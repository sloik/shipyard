//go:build !windows

package main

import (
	"os"
	"syscall"
)

// lockFileExclusive takes a non-blocking exclusive lock on f; it fails if
// another process already holds the lock.
func lockFileExclusive(f *os.File) error {
	return syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
}

func unlockFile(f *os.File) error {
	return syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
}
