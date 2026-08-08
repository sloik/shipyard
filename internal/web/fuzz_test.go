package web

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/sloik/shipyard/internal/capture"
)

func FuzzTrafficQueryFilter(f *testing.F) {
	for _, seed := range []string{
		``, `page=`, `page=0&page_size=-1`, `page=999999999999999999999&page_size=999999999999999999999`,
		`page=1&page_size=200&offset=0`, `from_ts=invalid&to_ts=-1`,
		`server=%E6%9C%8D%E5%8A%A1%E5%99%A8&method=tools%2Flist&search=%00`,
		`page=1&page=2&page_size=50&direction=client%3Eserver`,
	} {
		f.Add(seed)
	}

	srv := newTestServer(f)
	f.Fuzz(func(t *testing.T, rawQuery string) {
		if len(rawQuery) > 8*1024 {
			t.Skip()
		}
		requestURL := (&url.URL{Scheme: "http", Host: "fuzz.local", Path: "/api/traffic", RawQuery: rawQuery}).String()
		req, err := http.NewRequest(http.MethodGet, requestURL, nil)
		if err != nil {
			return
		}
		w := httptest.NewRecorder()
		srv.handleTraffic(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("traffic query returned status %d for %q", w.Code, rawQuery)
		}
		var page capture.TrafficPage
		if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
			t.Fatalf("traffic query returned invalid JSON for %q: %v", rawQuery, err)
		}
		if page.Page < 1 || page.PageSize < 1 || page.PageSize > 200 {
			t.Fatalf("traffic query escaped pagination bounds for %q: %+v", rawQuery, page)
		}
		if strings.Contains(w.Body.String(), "internal error") {
			t.Fatalf("traffic query returned internal error for %q", rawQuery)
		}
	})
}
