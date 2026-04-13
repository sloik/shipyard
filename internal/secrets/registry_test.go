package secrets

import (
	"context"
	"errors"
	"testing"
)

// mockResolver is a test double for SecretResolver.
type mockResolver struct {
	canResolveFunc func(string) bool
	resolveFunc    func(context.Context, string) (string, error)
	called         bool
}

func (m *mockResolver) CanResolve(ref string) bool {
	return m.canResolveFunc(ref)
}

func (m *mockResolver) Resolve(ctx context.Context, ref string) (string, error) {
	m.called = true
	return m.resolveFunc(ctx, ref)
}

func TestRegistry_FallbackToPlainText(t *testing.T) {
	reg := &Registry{}
	// Register a resolver that never claims any ref
	reg.Register(&mockResolver{
		canResolveFunc: func(string) bool { return false },
		resolveFunc:    func(context.Context, string) (string, error) { return "", nil },
	})

	ref := "plain-api-key-value"
	got, err := reg.Resolve(context.Background(), ref)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != ref {
		t.Errorf("Resolve(%q) = %q, want %q (plain passthrough)", ref, got, ref)
	}
}

func TestRegistry_FirstMatchWins(t *testing.T) {
	reg := &Registry{}

	first := &mockResolver{
		canResolveFunc: func(ref string) bool { return true }, // always claims
		resolveFunc: func(_ context.Context, _ string) (string, error) {
			return "from-first", nil
		},
	}
	second := &mockResolver{
		canResolveFunc: func(ref string) bool { return true }, // also claims
		resolveFunc: func(_ context.Context, _ string) (string, error) {
			return "from-second", nil
		},
	}

	reg.Register(first)
	reg.Register(second)

	got, err := reg.Resolve(context.Background(), "some-ref")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "from-first" {
		t.Errorf("got %q, want %q", got, "from-first")
	}
	if second.called {
		t.Error("second resolver was called — only first should be called when first matches")
	}
}

func TestRegistry_ResolveError(t *testing.T) {
	reg := &Registry{}
	wantErr := errors.New("resolver failed")
	reg.Register(&mockResolver{
		canResolveFunc: func(string) bool { return true },
		resolveFunc: func(context.Context, string) (string, error) {
			return "", wantErr
		},
	})

	_, err := reg.Resolve(context.Background(), "ref")
	if !errors.Is(err, wantErr) {
		t.Errorf("got err %v, want %v", err, wantErr)
	}
}

func TestRegistry_EmptyFallback(t *testing.T) {
	// Empty registry — everything is plain text
	reg := &Registry{}
	ref := "just-a-string"
	got, err := reg.Resolve(context.Background(), ref)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != ref {
		t.Errorf("got %q, want %q", got, ref)
	}
}

func TestDefaultRegistry_Env(t *testing.T) {
	reg := DefaultRegistry("env")
	if reg == nil {
		t.Fatal("DefaultRegistry returned nil")
	}
	// Should have at least one resolver (env)
	if len(reg.resolvers) == 0 {
		t.Error("DefaultRegistry(env) has no resolvers")
	}
}

func TestDefaultRegistry_Auto(t *testing.T) {
	reg := DefaultRegistry("")
	if reg == nil {
		t.Fatal("DefaultRegistry returned nil")
	}
	if len(reg.resolvers) == 0 {
		t.Error("DefaultRegistry(auto) has no resolvers")
	}
}
