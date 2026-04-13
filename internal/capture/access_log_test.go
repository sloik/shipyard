package capture

import (
	"testing"
	"time"
)

func TestRecordAccess_Smoke(t *testing.T) {
	s := newTestStore(t)

	entry := AccessLogEntry{
		Timestamp:  time.Now(),
		TokenName:  "tok-abc",
		ServerName: "fs",
		ToolName:   "read_file",
		Status:     "ok",
		LogLevel:   "full",
	}
	s.RecordAccess(entry)

	page, err := s.GetAccessLog(AccessLogFilter{})
	if err != nil {
		t.Fatalf("GetAccessLog: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 row, got %d", page.TotalCount)
	}
	if len(page.Items) != 1 {
		t.Fatalf("expected 1 item, got %d", len(page.Items))
	}
	row := page.Items[0]
	if row.TokenName != "tok-abc" {
		t.Errorf("expected token_name=tok-abc, got %q", row.TokenName)
	}
	if row.ServerName != "fs" {
		t.Errorf("expected server_name=fs, got %q", row.ServerName)
	}
	if row.ToolName != "read_file" {
		t.Errorf("expected tool_name=read_file, got %q", row.ToolName)
	}
	if row.Status != "ok" {
		t.Errorf("expected status=ok, got %q", row.Status)
	}
}

func TestRecordAccess_LogLevelNone_NotInserted(t *testing.T) {
	s := newTestStore(t)

	s.RecordAccess(AccessLogEntry{
		Timestamp:  time.Now(),
		TokenName:  "tok-none",
		ServerName: "fs",
		ToolName:   "read_file",
		Status:     "ok",
		LogLevel:   "none",
	})

	page, err := s.GetAccessLog(AccessLogFilter{})
	if err != nil {
		t.Fatalf("GetAccessLog: %v", err)
	}
	if page.TotalCount != 0 {
		t.Errorf("expected 0 rows for log_level=none + status=ok, got %d", page.TotalCount)
	}
}

func TestRecordAccess_LogLevelNone_DeniedInserted(t *testing.T) {
	s := newTestStore(t)

	s.RecordAccess(AccessLogEntry{
		Timestamp:  time.Now(),
		TokenName:  "tok-security",
		ServerName: "fs",
		ToolName:   "delete_file",
		Status:     "denied",
		LogLevel:   "none",
	})

	page, err := s.GetAccessLog(AccessLogFilter{})
	if err != nil {
		t.Fatalf("GetAccessLog: %v", err)
	}
	if page.TotalCount != 1 {
		t.Errorf("expected 1 row for log_level=none + status=denied (security event), got %d", page.TotalCount)
	}
}

func TestRecordAccess_LogLevelStatusOnly_NoArgs(t *testing.T) {
	s := newTestStore(t)

	s.RecordAccess(AccessLogEntry{
		Timestamp:  time.Now(),
		TokenName:  "tok-status",
		ServerName: "fs",
		ToolName:   "write_file",
		Status:     "ok",
		ArgsJSON:   `{"path":"/tmp/x","content":"hello"}`,
		LogLevel:   "status_only",
	})

	page, err := s.GetAccessLog(AccessLogFilter{})
	if err != nil {
		t.Fatalf("GetAccessLog: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 row, got %d", page.TotalCount)
	}
	if page.Items[0].ArgsJSON != "" {
		t.Errorf("expected empty args_json for status_only, got %q", page.Items[0].ArgsJSON)
	}
}

func TestGetAccessLog_FilterByToken(t *testing.T) {
	s := newTestStore(t)

	s.RecordAccess(AccessLogEntry{TokenName: "alice", ServerName: "fs", ToolName: "list", Status: "ok", LogLevel: "full"})
	s.RecordAccess(AccessLogEntry{TokenName: "bob", ServerName: "fs", ToolName: "list", Status: "ok", LogLevel: "full"})
	s.RecordAccess(AccessLogEntry{TokenName: "alice", ServerName: "fs", ToolName: "read", Status: "ok", LogLevel: "full"})

	page, err := s.GetAccessLog(AccessLogFilter{TokenName: "alice"})
	if err != nil {
		t.Fatalf("GetAccessLog: %v", err)
	}
	if page.TotalCount != 2 {
		t.Errorf("expected 2 rows for alice, got %d", page.TotalCount)
	}
	for _, row := range page.Items {
		if row.TokenName != "alice" {
			t.Errorf("expected token_name=alice, got %q", row.TokenName)
		}
	}
}

func TestGetAccessLog_FilterByStatus(t *testing.T) {
	s := newTestStore(t)

	s.RecordAccess(AccessLogEntry{TokenName: "tok", ServerName: "fs", ToolName: "a", Status: "ok", LogLevel: "full"})
	s.RecordAccess(AccessLogEntry{TokenName: "tok", ServerName: "fs", ToolName: "b", Status: "denied", LogLevel: "full"})
	s.RecordAccess(AccessLogEntry{TokenName: "tok", ServerName: "fs", ToolName: "c", Status: "error", LogLevel: "full"})

	page, err := s.GetAccessLog(AccessLogFilter{Status: "denied"})
	if err != nil {
		t.Fatalf("GetAccessLog: %v", err)
	}
	if page.TotalCount != 1 {
		t.Errorf("expected 1 denied row, got %d", page.TotalCount)
	}
	if len(page.Items) > 0 && page.Items[0].Status != "denied" {
		t.Errorf("expected status=denied, got %q", page.Items[0].Status)
	}
}

func TestGetAccessLog_Pagination(t *testing.T) {
	s := newTestStore(t)

	for i := 0; i < 5; i++ {
		s.RecordAccess(AccessLogEntry{
			TokenName:  "tok",
			ServerName: "fs",
			ToolName:   "tool",
			Status:     "ok",
			LogLevel:   "full",
		})
	}

	// First page
	page1, err := s.GetAccessLog(AccessLogFilter{Limit: 2, Offset: 0})
	if err != nil {
		t.Fatalf("GetAccessLog page1: %v", err)
	}
	if page1.TotalCount != 5 {
		t.Errorf("expected total=5, got %d", page1.TotalCount)
	}
	if len(page1.Items) != 2 {
		t.Errorf("expected 2 items in page1, got %d", len(page1.Items))
	}

	// Second page
	page2, err := s.GetAccessLog(AccessLogFilter{Limit: 2, Offset: 2})
	if err != nil {
		t.Fatalf("GetAccessLog page2: %v", err)
	}
	if len(page2.Items) != 2 {
		t.Errorf("expected 2 items in page2, got %d", len(page2.Items))
	}

	// Last page (partial)
	page3, err := s.GetAccessLog(AccessLogFilter{Limit: 2, Offset: 4})
	if err != nil {
		t.Fatalf("GetAccessLog page3: %v", err)
	}
	if len(page3.Items) != 1 {
		t.Errorf("expected 1 item in page3, got %d", len(page3.Items))
	}
}

func TestGetAccessLogStats_Empty(t *testing.T) {
	s := newTestStore(t)

	stats, err := s.GetAccessLogStats()
	if err != nil {
		t.Fatalf("GetAccessLogStats: %v", err)
	}
	if stats.TotalCalls != 0 {
		t.Errorf("expected TotalCalls=0, got %d", stats.TotalCalls)
	}
	if stats.ErrorRate != 0.0 {
		t.Errorf("expected ErrorRate=0.0, got %f", stats.ErrorRate)
	}
	if stats.TopTools == nil {
		t.Error("expected non-nil TopTools slice")
	}
	if stats.PerToken == nil {
		t.Error("expected non-nil PerToken slice")
	}
	if len(stats.TopTools) != 0 {
		t.Errorf("expected empty TopTools, got %d entries", len(stats.TopTools))
	}
	if len(stats.PerToken) != 0 {
		t.Errorf("expected empty PerToken, got %d entries", len(stats.PerToken))
	}
}

func TestGetAccessLogStats_WithData(t *testing.T) {
	s := newTestStore(t)

	// 3 ok calls for fs/read_file by alice
	for i := 0; i < 3; i++ {
		s.RecordAccess(AccessLogEntry{TokenName: "alice", ServerName: "fs", ToolName: "read_file", Status: "ok", LogLevel: "full"})
	}
	// 2 denied calls for fs/delete_file by bob
	for i := 0; i < 2; i++ {
		s.RecordAccess(AccessLogEntry{TokenName: "bob", ServerName: "fs", ToolName: "delete_file", Status: "denied", LogLevel: "full"})
	}

	stats, err := s.GetAccessLogStats()
	if err != nil {
		t.Fatalf("GetAccessLogStats: %v", err)
	}

	if stats.TotalCalls != 5 {
		t.Errorf("expected TotalCalls=5, got %d", stats.TotalCalls)
	}

	// Error rate: 2 bad / 5 total = 0.4
	expectedRate := 2.0 / 5.0
	if stats.ErrorRate < expectedRate-0.001 || stats.ErrorRate > expectedRate+0.001 {
		t.Errorf("expected ErrorRate≈%.3f, got %.3f", expectedRate, stats.ErrorRate)
	}

	if len(stats.TopTools) == 0 {
		t.Error("expected non-empty TopTools")
	}

	if len(stats.PerToken) == 0 {
		t.Error("expected non-empty PerToken")
	}

	// Verify alice has 0 denied rate
	for _, pt := range stats.PerToken {
		if pt.TokenName == "alice" {
			if pt.Count != 3 {
				t.Errorf("alice: expected count=3, got %d", pt.Count)
			}
			if pt.DeniedRate != 0.0 {
				t.Errorf("alice: expected denied_rate=0.0, got %f", pt.DeniedRate)
			}
		}
		if pt.TokenName == "bob" {
			if pt.Count != 2 {
				t.Errorf("bob: expected count=2, got %d", pt.Count)
			}
			if pt.DeniedRate < 0.99 {
				t.Errorf("bob: expected denied_rate≈1.0, got %f", pt.DeniedRate)
			}
		}
	}
}
