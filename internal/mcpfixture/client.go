// Portions of this file are adapted from the Go MCP SDK v1.8.0
// conformance/everything-client (Copyright 2025 The Go MCP SDK Authors; the
// upstream file is governed by an MIT-style license, the SDK repository is
// Apache-2.0 with MIT for un-relicensed contributions; see
// docs/dependencies/go-sdk.md). The adaptation covers the
// pinned conformance CLI's client "core" suite.

package mcpfixture

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"slices"
	"sort"

	"github.com/modelcontextprotocol/go-sdk/auth"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/modelcontextprotocol/go-sdk/oauthex"

	"github.com/sloik/shipyard/internal/mcpcore"
)

type oauthHandler = auth.OAuthHandler

type scenarioFunc func(ctx context.Context, era mcpcore.Era, serverURL string, conformance map[string]any) error

var clientScenarios = map[string]scenarioFunc{
	"initialize":                          runInitialize,
	"tools_call":                          runCallNamedTool("add_numbers", map[string]any{"a": 5, "b": 3}, nil),
	"elicitation-sep1034-client-defaults": runCallNamedTool("test_client_elicitation_defaults", map[string]any{}, acceptEmptyElicitation),
	"sse-retry":                           runCallNamedTool("test_reconnection", map[string]any{}, nil),
}

func init() {
	for _, name := range []string{
		"auth/metadata-default", "auth/metadata-var1", "auth/metadata-var2", "auth/metadata-var3",
		"auth/basic-cimd", "auth/scope-from-www-authenticate", "auth/scope-from-scopes-supported",
		"auth/scope-omitted-when-undefined", "auth/scope-step-up", "auth/scope-retry-limit",
		"auth/token-endpoint-auth-basic", "auth/token-endpoint-auth-post", "auth/token-endpoint-auth-none",
		"auth/pre-registration", "auth/2025-03-26-oauth-metadata-backcompat", "auth/2025-03-26-oauth-endpoint-fallback",
	} {
		clientScenarios[name] = runAuth
	}
}

// ClientScenarios lists the conformance client scenarios the fixture client
// implements, sorted.
func ClientScenarios() []string {
	names := make([]string, 0, len(clientScenarios))
	for name := range clientScenarios {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// RunClientScenario runs one conformance client scenario as a fixture client
// of the given era. conformance is the decoded MCP_CONFORMANCE_CONTEXT.
func RunClientScenario(ctx context.Context, era mcpcore.Era, name, serverURL string, conformance map[string]any) error {
	run, ok := clientScenarios[name]
	if !ok {
		return fmt.Errorf("unknown conformance scenario %q (have %v)", name, ClientScenarios())
	}
	return run(ctx, era, serverURL, conformance)
}

func runInitialize(ctx context.Context, era mcpcore.Era, serverURL string, _ map[string]any) error {
	cs, err := connect(ctx, era, serverURL, nil, connectOptions{})
	if err != nil {
		return err
	}
	defer cs.Close()
	if _, err := cs.ListTools(ctx, nil); err != nil {
		return fmt.Errorf("list tools: %w", err)
	}
	return nil
}

func acceptEmptyElicitation(context.Context, *mcp.ElicitRequest) (*mcp.ElicitResult, error) {
	return &mcp.ElicitResult{Action: "accept", Content: map[string]any{}}, nil
}

func runCallNamedTool(tool string, args map[string]any, elicit func(context.Context, *mcp.ElicitRequest) (*mcp.ElicitResult, error)) scenarioFunc {
	return func(ctx context.Context, era mcpcore.Era, serverURL string, _ map[string]any) error {
		cs, err := connect(ctx, era, serverURL, nil, connectOptions{client: &mcp.ClientOptions{ElicitationHandler: elicit}})
		if err != nil {
			return err
		}
		defer cs.Close()
		tools, err := cs.ListTools(ctx, nil)
		if err != nil {
			return fmt.Errorf("list tools: %w", err)
		}
		if !slices.ContainsFunc(tools.Tools, func(t *mcp.Tool) bool { return t.Name == tool }) {
			return fmt.Errorf("tool %q not found", tool)
		}
		if _, err := cs.CallTool(ctx, &mcp.CallToolParams{Name: tool, Arguments: args}); err != nil {
			return fmt.Errorf("call %s: %w", tool, err)
		}
		return nil
	}
}

const conformanceRedirect = "http://localhost:3000/callback"

// fetchAuthorizationCode follows the conformance authorization server's
// immediate redirect and returns the code, state and issuer it carries.
func fetchAuthorizationCode(ctx context.Context, args *auth.AuthorizationArgs) (*auth.AuthorizationResult, error) {
	client := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, args.URL, nil)
	if err != nil {
		return nil, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	loc, err := url.Parse(resp.Header.Get("Location"))
	if err != nil {
		return nil, fmt.Errorf("parse authorization redirect: %w", err)
	}
	q := loc.Query()
	return &auth.AuthorizationResult{Code: q.Get("code"), State: q.Get("state"), Iss: q.Get("iss")}, nil
}

func runAuth(ctx context.Context, era mcpcore.Era, serverURL string, conformance map[string]any) error {
	cfg := &auth.AuthorizationCodeHandlerConfig{
		RedirectURL:                    conformanceRedirect,
		AuthorizationCodeFetcher:       fetchAuthorizationCode,
		ClientIDMetadataDocumentConfig: &auth.ClientIDMetadataDocumentConfig{URL: "https://conformance-test.local/client-metadata.json"},
		DynamicClientRegistrationConfig: &auth.DynamicClientRegistrationConfig{
			Metadata: &oauthex.ClientRegistrationMetadata{RedirectURIs: []string{conformanceRedirect}},
		},
	}
	if id, ok := conformance["client_id"].(string); ok {
		if secret, ok := conformance["client_secret"].(string); ok {
			cfg.PreregisteredClient = &oauthex.ClientCredentials{ClientID: id, ClientSecretAuth: &oauthex.ClientSecretAuth{ClientSecret: secret}}
		}
	}
	handler, err := auth.NewAuthorizationCodeHandler(cfg)
	if err != nil {
		return fmt.Errorf("create OAuth handler: %w", err)
	}
	cs, err := connect(ctx, era, serverURL, nil, connectOptions{oauth: handler})
	if err != nil {
		return err
	}
	defer cs.Close()
	if _, err := cs.ListTools(ctx, nil); err != nil {
		return fmt.Errorf("list tools: %w", err)
	}
	if _, err := cs.CallTool(ctx, &mcp.CallToolParams{Name: "test-tool", Arguments: map[string]any{}}); err != nil {
		return fmt.Errorf("call test-tool: %w", err)
	}
	return nil
}
