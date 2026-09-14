# Language Conventions

Covers Go and Rust programming language conventions, idioms, and best practices.

## Go Conventions

### 🔴 HARD RULEs

- `gofmt` before every commit — non-negotiable formatting
- Never use `init()` functions — prefer explicit initialization
- Always handle errors — never use `_` to discard errors
- Use `context.Context` as first parameter in any blocking/IO function
- Prefer `go test -race` — always test with the race detector

### Idioms

- Accept interfaces, return structs
- Use `sync.Mutex` or `sync.RWMutex` for concurrency, not channels (channels are for orchestration)
- Favor composition over inheritance via embedding
- `error` values are values — create custom error types with `fmt.Errorf("context: %w", err)`

## Rust Conventions

### 🔴 HARD RULEs

- No `unwrap()` or `expect()` in production code — use proper error handling with `?` operator
- All public APIs must have doc comments (`///`)
- `cargo clippy` must pass before commits
- Use `thiserror` for library error types, `anyhow` for application code
- Prefer `impl Trait` in argument positions over generics where possible

### Idioms

- Builder pattern for complex constructors
- Newtype pattern for type safety: `struct UserId(i64)`
- Use `Into<>` for flexible function parameters
- Prefer `enum` over boolean flags for clarity
