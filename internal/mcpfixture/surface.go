// Portions of this file are adapted from the Go MCP SDK v1.8.0
// conformance/everything-server (Copyright 2025 The Go MCP SDK Authors; the
// upstream file is governed by an MIT-style license, the SDK repository is
// Apache-2.0 with MIT for un-relicensed contributions; see
// docs/dependencies/go-sdk.md). The adaptation keeps only the
// surface exercised by the pinned conformance CLI's 2025-11-25 server suite.
//
// SA1019 exception (SPEC-BUG-181, this file only): the 2025-11-25 conformance
// suite exercises sampling and logging, which SEP-2577 deprecates for
// 2026-07-28 but which remain in their deprecation window. Review when the
// legacy era is retired.
//
//lint:file-ignore SA1019 legacy-era conformance surface exercises SEP-2577-deprecated sampling/logging.

package mcpfixture

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/jsonschema-go/jsonschema"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/yosida95/uritemplate/v3"
)

// Minimal 1x1 PNG and silent WAV used by the conformance content scenarios.
const (
	testImageBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
	testAudioBase64 = "UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAAB9AAACABAAZGF0YQIAAAA="
	watchedURI      = "test://watched-resource"
)

var (
	imageData, _    = base64.StdEncoding.DecodeString(testImageBase64)
	audioData, _    = base64.StdEncoding.DecodeString(testAudioBase64)
	templatePattern = uritemplate.MustNew("test://template/{id}/data")
)

func text(s string) *mcp.CallToolResult {
	return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: s}}}
}

func constTool(result func() *mcp.CallToolResult) mcp.ToolHandlerFor[any, any] {
	return func(context.Context, *mcp.CallToolRequest, any) (*mcp.CallToolResult, any, error) {
		return result(), nil, nil
	}
}

func registerConformanceSurface(server *mcp.Server) {
	registerContentTools(server)
	registerInteractiveTools(server)
	registerResources(server)
	registerPrompts(server)
}

func registerContentTools(server *mcp.Server) {
	mcp.AddTool(server, &mcp.Tool{Name: "test_simple_text", Description: "Simple text content"},
		constTool(func() *mcp.CallToolResult { return text("This is a simple text response for testing.") }))
	mcp.AddTool(server, &mcp.Tool{Name: "test_image_content", Description: "Image content"},
		constTool(func() *mcp.CallToolResult {
			return &mcp.CallToolResult{Content: []mcp.Content{&mcp.ImageContent{Data: imageData, MIMEType: "image/png"}}}
		}))
	mcp.AddTool(server, &mcp.Tool{Name: "test_audio_content", Description: "Audio content"},
		constTool(func() *mcp.CallToolResult {
			return &mcp.CallToolResult{Content: []mcp.Content{&mcp.AudioContent{Data: audioData, MIMEType: "audio/wav"}}}
		}))
	mcp.AddTool(server, &mcp.Tool{Name: "test_embedded_resource", Description: "Embedded resource content"},
		constTool(func() *mcp.CallToolResult {
			return &mcp.CallToolResult{Content: []mcp.Content{&mcp.EmbeddedResource{Resource: &mcp.ResourceContents{
				URI: "test://embedded-resource", MIMEType: "text/plain", Text: "This is an embedded resource",
			}}}}
		}))
	mcp.AddTool(server, &mcp.Tool{Name: "test_multiple_content_types", Description: "Text, image and resource content"},
		constTool(func() *mcp.CallToolResult {
			return &mcp.CallToolResult{Content: []mcp.Content{
				&mcp.TextContent{Text: "This is text content"},
				&mcp.ImageContent{Data: imageData, MIMEType: "image/png"},
				&mcp.EmbeddedResource{Resource: &mcp.ResourceContents{
					URI: "test://embedded-in-multiple", MIMEType: "text/plain", Text: "This is an embedded resource",
				}},
			}}
		}))
	mcp.AddTool(server, &mcp.Tool{Name: "test_error_handling", Description: "Tool-level error"},
		func(context.Context, *mcp.CallToolRequest, any) (*mcp.CallToolResult, any, error) {
			return nil, nil, errors.New("this tool intentionally returns an error for testing")
		})
	mcp.AddTool(server, &mcp.Tool{
		Name:        "json_schema_2020_12_tool",
		Description: "Tool with JSON Schema 2020-12 features",
		InputSchema: json.RawMessage(`{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object",` +
			`"$defs":{"address":{"type":"object","properties":{"street":{"type":"string"},"city":{"type":"string"}}}},` +
			`"properties":{"name":{"type":"string"},"address":{"$ref":"#/$defs/address"}},"additionalProperties":false}`),
	}, func(_ context.Context, _ *mcp.CallToolRequest, in json.RawMessage) (*mcp.CallToolResult, any, error) {
		return text(fmt.Sprintf("JSON Schema 2020-12 tool called with: %s", in)), nil, nil
	})
}

type samplingInput struct {
	Prompt string `json:"prompt" jsonschema:"The prompt to send to the LLM"`
}

type elicitationInput struct {
	Message string `json:"message" jsonschema:"The message to show the user"`
}

func registerInteractiveTools(server *mcp.Server) {
	mcp.AddTool(server, &mcp.Tool{Name: "test_tool_with_logging", Description: "Emits log messages"},
		func(ctx context.Context, req *mcp.CallToolRequest, _ any) (*mcp.CallToolResult, any, error) {
			for _, msg := range []string{"Tool execution started", "Tool processing data", "Tool execution completed"} {
				_ = req.Session.Log(ctx, &mcp.LoggingMessageParams{Level: "info", Data: msg})
				time.Sleep(50 * time.Millisecond)
			}
			return text("Tool with logging executed successfully"), nil, nil
		})
	mcp.AddTool(server, &mcp.Tool{Name: "test_tool_with_progress", Description: "Reports progress"},
		func(ctx context.Context, req *mcp.CallToolRequest, _ any) (*mcp.CallToolResult, any, error) {
			token := req.Params.GetProgressToken()
			for _, p := range []float64{0, 50, 100} {
				_ = req.Session.NotifyProgress(ctx, &mcp.ProgressNotificationParams{
					ProgressToken: token, Progress: p, Total: 100, Message: fmt.Sprintf("Completed step %.0f of 100", p),
				})
				time.Sleep(50 * time.Millisecond)
			}
			return text(fmt.Sprintf("%v", token)), nil, nil
		})
	mcp.AddTool(server, &mcp.Tool{Name: "test_sampling", Description: "Server-initiated sampling"},
		func(ctx context.Context, req *mcp.CallToolRequest, in samplingInput) (*mcp.CallToolResult, any, error) {
			res, err := req.Session.CreateMessage(ctx, &mcp.CreateMessageParams{
				Messages:  []*mcp.SamplingMessage{{Role: "user", Content: &mcp.TextContent{Text: in.Prompt}}},
				MaxTokens: 100,
			})
			if err != nil {
				return nil, nil, fmt.Errorf("sampling failed: %w", err)
			}
			reply := "(non-text response)"
			if tc, ok := res.Content.(*mcp.TextContent); ok {
				reply = tc.Text
			}
			return text("LLM response: " + reply), nil, nil
		})
	mcp.AddTool(server, &mcp.Tool{Name: "test_elicitation", Description: "Server-initiated elicitation"},
		func(ctx context.Context, req *mcp.CallToolRequest, in elicitationInput) (*mcp.CallToolResult, any, error) {
			return elicit(ctx, req, in.Message, &jsonschema.Schema{
				Type:       "object",
				Properties: map[string]*jsonschema.Schema{"username": {Type: "string", Description: "Your preferred username"}},
				Required:   []string{"username"},
			})
		})
	mcp.AddTool(server, &mcp.Tool{Name: "test_elicitation_sep1034_defaults", Description: "Elicitation defaults (SEP-1034)"},
		func(ctx context.Context, req *mcp.CallToolRequest, _ any) (*mcp.CallToolResult, any, error) {
			return elicit(ctx, req, "Test defaults for primitives", map[string]any{
				"type": "object",
				"properties": map[string]any{
					"name":     map[string]any{"type": "string", "description": "User name", "default": "John Doe"},
					"age":      map[string]any{"type": "integer", "description": "User age", "default": 30},
					"score":    map[string]any{"type": "number", "description": "User score", "default": 95.5},
					"status":   map[string]any{"type": "string", "description": "User status", "enum": []string{"active", "inactive", "pending"}, "default": "active"},
					"verified": map[string]any{"type": "boolean", "description": "Verification status", "default": true},
				},
			})
		})
	mcp.AddTool(server, &mcp.Tool{Name: "test_elicitation_sep1330_enums", Description: "Elicitation enums (SEP-1330)"},
		func(ctx context.Context, req *mcp.CallToolRequest, _ any) (*mcp.CallToolResult, any, error) {
			titled := []map[string]any{
				{"const": "value1", "title": "First Option"},
				{"const": "value2", "title": "Second Option"},
				{"const": "value3", "title": "Third Option"},
			}
			options := []string{"option1", "option2", "option3"}
			return elicit(ctx, req, "Test enum schemas", map[string]any{
				"type": "object",
				"properties": map[string]any{
					"untitledSingle": map[string]any{"type": "string", "enum": options},
					"titledSingle":   map[string]any{"type": "string", "oneOf": titled},
					"legacyEnum":     map[string]any{"type": "string", "enum": []string{"opt1", "opt2", "opt3"}, "enumNames": []string{"Option One", "Option Two", "Option Three"}},
					"untitledMulti":  map[string]any{"type": "array", "minItems": 1, "maxItems": 3, "items": map[string]any{"type": "string", "enum": options}},
					"titledMulti":    map[string]any{"type": "array", "minItems": 1, "maxItems": 3, "items": map[string]any{"type": "string", "anyOf": titled}},
				},
			})
		})
}

func elicit(ctx context.Context, req *mcp.CallToolRequest, message string, schema any) (*mcp.CallToolResult, any, error) {
	res, err := req.Session.Elicit(ctx, &mcp.ElicitParams{Message: message, RequestedSchema: schema})
	if err != nil {
		return nil, nil, fmt.Errorf("elicitation failed: %w", err)
	}
	return text(fmt.Sprintf("Elicitation result: action=%s, content=%v", res.Action, res.Content)), nil, nil
}

func resourceText(uri, mime, body string) *mcp.ReadResourceResult {
	return &mcp.ReadResourceResult{Contents: []*mcp.ResourceContents{{URI: uri, MIMEType: mime, Text: body}}}
}

func registerResources(server *mcp.Server) {
	server.AddResource(&mcp.Resource{Name: "static-text", MIMEType: "text/plain", URI: "test://static-text"},
		func(_ context.Context, req *mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
			return resourceText(req.Params.URI, "text/plain", "This is the content of the static text resource."), nil
		})
	server.AddResource(&mcp.Resource{Name: "static-binary", MIMEType: "image/png", URI: "test://static-binary"},
		func(_ context.Context, req *mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
			return &mcp.ReadResourceResult{Contents: []*mcp.ResourceContents{{URI: req.Params.URI, MIMEType: "image/png", Blob: imageData}}}, nil
		})
	server.AddResourceTemplate(&mcp.ResourceTemplate{Name: "template", MIMEType: "application/json", URITemplate: "test://template/{id}/data"},
		func(_ context.Context, req *mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
			id := ""
			if m := templatePattern.Regexp().FindStringSubmatch(req.Params.URI); len(m) > 1 {
				id = m[1]
			}
			body := fmt.Sprintf(`{"id": "%s", "templateTest": true, "data": "Data for ID: %s"}`, id, id)
			return resourceText(req.Params.URI, "application/json", body), nil
		})
	server.AddResource(&mcp.Resource{Name: "watched-resource", MIMEType: "text/plain", URI: watchedURI},
		func(_ context.Context, req *mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
			return resourceText(req.Params.URI, "text/plain", "Watched resource content"), nil
		})
}

func userPrompt(description string, contents ...mcp.Content) *mcp.GetPromptResult {
	res := &mcp.GetPromptResult{Description: description}
	for _, c := range contents {
		res.Messages = append(res.Messages, &mcp.PromptMessage{Role: "user", Content: c})
	}
	return res
}

func registerPrompts(server *mcp.Server) {
	server.AddPrompt(&mcp.Prompt{Name: "test_simple_prompt", Description: "A simple prompt without arguments"},
		func(context.Context, *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
			return userPrompt("A simple test prompt", &mcp.TextContent{Text: "This is a simple prompt for testing."}), nil
		})
	server.AddPrompt(&mcp.Prompt{Name: "test_prompt_with_arguments", Description: "A prompt with required arguments",
		Arguments: []*mcp.PromptArgument{
			{Name: "arg1", Description: "First test argument", Required: true},
			{Name: "arg2", Description: "Second test argument", Required: true},
		}},
		func(_ context.Context, req *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
			return userPrompt("A prompt with arguments", &mcp.TextContent{
				Text: fmt.Sprintf("Prompt with arguments: arg1='%s', arg2='%s'", req.Params.Arguments["arg1"], req.Params.Arguments["arg2"]),
			}), nil
		})
	server.AddPrompt(&mcp.Prompt{Name: "test_prompt_with_embedded_resource", Description: "A prompt with an embedded resource",
		Arguments: []*mcp.PromptArgument{{Name: "resourceUri", Description: "URI of the resource to embed", Required: true}}},
		func(_ context.Context, req *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
			return userPrompt("A prompt with an embedded resource",
				&mcp.EmbeddedResource{Resource: &mcp.ResourceContents{URI: req.Params.Arguments["resourceUri"], MIMEType: "text/plain", Text: "Embedded resource content for testing."}},
				&mcp.TextContent{Text: "Please process the embedded resource above."}), nil
		})
	server.AddPrompt(&mcp.Prompt{Name: "test_prompt_with_image", Description: "A prompt with image content"},
		func(context.Context, *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
			return userPrompt("A prompt with an image",
				&mcp.ImageContent{Data: imageData, MIMEType: "image/png"},
				&mcp.TextContent{Text: "Please analyze the image above."}), nil
		})
}

func completionHandler(context.Context, *mcp.CompleteRequest) (*mcp.CompleteResult, error) {
	return &mcp.CompleteResult{Completion: mcp.CompletionResultDetails{Values: []string{}, Total: 0}}, nil
}

// registerFixtureTools adds the tools the golden wire cases rely on.
func registerFixtureTools(server *mcp.Server, obs *Observer) {
	mcp.AddTool(server, &mcp.Tool{Name: ToolEchoMeta, Description: "Echoes request _meta into result _meta"},
		func(_ context.Context, req *mcp.CallToolRequest, _ any) (*mcp.CallToolResult, any, error) {
			res := text("meta echoed")
			res.Meta = mcp.Meta{}
			for k, v := range req.Params.GetMeta() {
				if k == "x.example/trace" {
					res.Meta[k] = v
				}
			}
			return res, nil, nil
		})
	mcp.AddTool(server, &mcp.Tool{Name: ToolError, Description: "Returns a tool-level error result"},
		func(context.Context, *mcp.CallToolRequest, any) (*mcp.CallToolResult, any, error) {
			return nil, nil, errors.New("fixture tool failure")
		})
	mcp.AddTool(server, &mcp.Tool{Name: ToolSlow, Description: "Blocks until cancelled"},
		func(ctx context.Context, _ *mcp.CallToolRequest, _ any) (*mcp.CallToolResult, any, error) {
			obs.markStarted()
			select {
			case <-ctx.Done():
				obs.markCancelled()
				return nil, nil, ctx.Err()
			case <-obs.releaseCh():
				return text("slow tool released"), nil, nil
			case <-time.After(30 * time.Second):
				return text("slow tool finished"), nil, nil
			}
		})
}
