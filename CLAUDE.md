# Repository notes

## Item 002: Show how many are left

Keep the remaining count derived on every render from the `Todo.done` flags in `todos` and emitted server-side as `<p class="remaining">` directly under the `<h1>` in `app/main.py`'s `render()`, with exactly `N left`, `1 left` for one, and `Nothing left` for zero; do not add a separate counter or client-side update, because a stored count would drift whenever `reset()`, `add()`, or the done endpoint changes the list, and the tests assert these exact strings in the returned HTML. Detail: `specs/002-show-how-many-are-left/spec.html`.
