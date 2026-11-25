# Testing, errors and logging

How to write tests, handle errors, and log in code you write or change.

Match the project's test framework, layout and helpers first.

## Testing

- Test behaviour through the public interface, not implementation details.
- Arrange, Act, Assert. One reason to fail per test.
- Deterministic: no real network, clock, or randomness. Fake, freeze, or seed them.
- Name tests by behaviour: `rejects_expired_token`, not `test_validate_2`.
- Test pyramid: many unit tests, fewer integration, few end-to-end.
- Bug fix: write the failing regression test first, then fix.
- Never delete, skip, or weaken a failing test to go green. Report it instead.
- Do not run migrations or tests that create databases or network resources unless the
  brief allows it. Say what you did not run.
- Fixtures small and local to the test. No shared mutable state between tests.
- Run the tests you touched plus the nearest suite. Report the command and the result.

## Errors

- Fail fast at boundaries: validate input where it enters (request, CLI, file, queue).
- Never swallow exceptions. No empty `catch`/`except`; no bare `except:`.
- Catch only what you can handle. Otherwise let it propagate.
- Wrap with context when rethrowing, keep the cause (`raise ... from e`, `%w`, `cause`).
- Use typed or custom errors where the language supports them; no string matching.
- User-facing messages are safe: no stack traces, SQL, paths, secrets, or internal ids.
- HTTP error bodies follow `api.md` (RFC 9457 problem details).
- Clean up resources on every path (`with`, `try/finally`, `defer`, `using`).

## Logging

- Use the project's logger. Structured fields over string concatenation.
- Levels: `debug` detail for developers, `info` normal events, `warn` recoverable or
  unexpected, `error` failed operation needing attention. Use them consistently.
- Never log secrets, tokens, passwords, full card numbers, or full personal data; mask or
  hash identifiers if needed (see `security.md`).
- Include the correlation or request id if the project has one.
- Log once, where the error is handled. Do not log and rethrow at every layer.
- No `print`/`console.log` left in committed code unless it is the project's logging.

Sources: Practical Test Pyramid https://martinfowler.com/articles/practical-test-pyramid.html · RFC 9457 https://www.rfc-editor.org/rfc/rfc9457 · OWASP Logging Cheat Sheet https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html · OWASP Error Handling https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html
