package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	Method  string          `json:"method"`
	ID      json.RawMessage `json:"id,omitempty"`
	Params  json.RawMessage `json:"params,omitempty"`
}

func main() {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		var req rpcRequest
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			continue
		}
		if len(req.ID) == 0 {
			continue
		}

		var result any
		switch req.Method {
		case "tools/list":
			result = map[string]any{
				"tools": []map[string]any{
					{
						"name":        "echo",
						"description": "echoes the supplied arguments",
					},
				},
			}
		case "tools/call":
			result = map[string]any{
				"content": []map[string]any{
					{
						"type": "text",
						"text": fmt.Sprintf("stub child handled %s", string(req.Params)),
					},
				},
			}
		default:
			result = map[string]any{
				"ok":     true,
				"method": req.Method,
			}
		}

		payload, err := json.Marshal(map[string]any{
			"jsonrpc": "2.0",
			"id":      json.RawMessage(req.ID),
			"result":  result,
		})
		if err != nil {
			continue
		}
		fmt.Fprintln(os.Stdout, string(payload))
	}
}
