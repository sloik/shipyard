package capture

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

// jsonlFile is a size-capped, rotating append-only writer for the JSONL
// backup. It keeps a byte counter initialised from the file size at open and
// rotates (.N -> .N+1, current -> .1) before a write that would exceed max.
// The file is always closed before any rename/delete so no fd ever holds a
// dropped inode.
type jsonlFile struct {
	mu   sync.Mutex
	path string
	max  int64
	keep int
	f    *os.File
	size int64
}

// openRotatingJSONL opens (creating if needed) the JSONL backup. An existing
// file larger than max is trimmed to its last max bytes (from a line
// boundary) so a legacy oversized file is actually freed.
func openRotatingJSONL(path string, max int64, keep int) (*jsonlFile, error) {
	w := &jsonlFile{path: path, max: max, keep: keep}
	if max > 0 {
		if info, err := os.Stat(path); err == nil && info.Size() > max {
			if err := trimToTail(path, max); err != nil {
				slog.Warn("jsonl: trimming oversized backup failed; discarding it", "path", path, "error", err)
				if terr := os.Truncate(path, 0); terr != nil {
					return nil, fmt.Errorf("truncate oversized jsonl: %w", terr)
				}
			}
		}
		w.removeStale()
	}
	if err := w.open(); err != nil {
		return nil, err
	}
	return w, nil
}

func (w *jsonlFile) open() error {
	f, err := openJSONLFile(w.path)
	if err != nil {
		return err
	}
	w.f = f
	w.size = 0
	if info, err := f.Stat(); err == nil {
		w.size = info.Size()
	}
	return nil
}

// Name returns the path of the current JSONL file.
func (w *jsonlFile) Name() string { return w.path }

// writeLine appends line plus a newline, rotating first when the write would
// push the current file past max.
func (w *jsonlFile) writeLine(line []byte) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.f == nil {
		if err := w.open(); err != nil {
			return err
		}
	}
	n := int64(len(line)) + 1
	if w.max > 0 && w.size > 0 && w.size+n > w.max {
		if err := w.rotateLocked(); err != nil {
			slog.Error("jsonl rotation failed", "error", err)
		}
		if w.f == nil {
			if err := w.open(); err != nil {
				return err
			}
		}
	}
	buf := make([]byte, 0, len(line)+1)
	buf = append(append(buf, line...), '\n')
	written, err := w.f.Write(buf)
	w.size += int64(written)
	return err
}

func (w *jsonlFile) rotatedName(i int) string { return w.path + "." + strconv.Itoa(i) }

// rotateLocked closes the current file, shifts the rotated set and reopens.
func (w *jsonlFile) rotateLocked() error {
	if w.f != nil {
		cerr := w.f.Close()
		w.f = nil
		if cerr != nil {
			slog.Warn("jsonl close before rotate", "error", cerr)
		}
	}
	var firstErr error
	note := func(err error) {
		if err != nil && !errors.Is(err, os.ErrNotExist) && firstErr == nil {
			firstErr = err
		}
	}
	if w.keep <= 0 {
		note(os.Remove(w.path))
	} else {
		note(os.Remove(w.rotatedName(w.keep)))
		for i := w.keep - 1; i >= 1; i-- {
			note(os.Rename(w.rotatedName(i), w.rotatedName(i+1)))
		}
		note(os.Rename(w.path, w.rotatedName(1)))
	}
	w.removeStale()
	if err := w.open(); err != nil {
		return errors.Join(firstErr, err)
	}
	return firstErr
}

// removeStale deletes rotated files beyond the keep count (for example left
// over after the keep setting was lowered).
func (w *jsonlFile) removeStale() {
	for _, p := range w.rotatedPaths() {
		idx, _ := strconv.Atoi(strings.TrimPrefix(p, w.path+"."))
		if idx > w.keep || w.keep <= 0 {
			_ = os.Remove(p)
		}
	}
}

func (w *jsonlFile) rotatedPaths() []string {
	return rotatedJSONLPaths(w.path)
}

// rotatedJSONLPaths lists path.<digits> siblings.
func rotatedJSONLPaths(path string) []string {
	matches, _ := filepath.Glob(path + ".*")
	var out []string
	for _, m := range matches {
		suffix := strings.TrimPrefix(m, path+".")
		if suffix == "" {
			continue
		}
		if _, err := strconv.Atoi(suffix); err == nil {
			out = append(out, m)
		}
	}
	return out
}

// totalBytes sums the current file and all rotated files.
func (w *jsonlFile) totalBytes() int64 {
	return jsonlTotalBytes(w.path)
}

func jsonlTotalBytes(path string) int64 {
	var total int64
	if info, err := os.Stat(path); err == nil {
		total += info.Size()
	}
	for _, p := range rotatedJSONLPaths(path) {
		if info, err := os.Stat(p); err == nil {
			total += info.Size()
		}
	}
	return total
}

func (w *jsonlFile) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.f == nil {
		return nil
	}
	err := w.f.Close()
	w.f = nil
	return err
}

// trimToTail rewrites path so it holds only its last <= max bytes, starting at
// a line boundary. The old inode is replaced by rename, so its space is freed
// once no fd holds it.
func trimToTail(path string, max int64) error {
	src, err := os.Open(path)
	if err != nil {
		return err
	}
	defer src.Close()
	info, err := src.Stat()
	if err != nil {
		return err
	}
	start := info.Size() - max
	if start < 0 {
		start = 0
	}
	// Seek one byte early: if that byte is '\n' the tail already starts on a
	// line boundary.
	seek := start - 1
	if seek < 0 {
		seek = 0
	}
	if _, err := src.Seek(seek, io.SeekStart); err != nil {
		return err
	}
	br := bufio.NewReaderSize(src, 1<<20)
	if start > 0 {
		for {
			_, err := br.ReadSlice('\n')
			if err == bufio.ErrBufferFull {
				continue
			}
			if err != nil && err != io.EOF {
				return err
			}
			break // consumed through the first newline (or hit EOF: no line start in the tail)
		}
	}
	tmp := path + ".trim.tmp"
	dst, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	if _, err := io.Copy(dst, br); err != nil {
		dst.Close()
		os.Remove(tmp)
		return err
	}
	if err := dst.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, path)
}
