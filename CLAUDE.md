# Repository notes

## Item 002: Show how many are left

Keep the remaining count derived on every render from the `Todo.done` flags in `todos` and emitted server-side as `<p class="remaining">` directly under the `<h1>` in `app/main.py`'s `render()`, with exactly `N left`, `1 left` for one, and `Nothing left` for zero; do not add a separate counter or client-side update, because a stored count would drift whenever `reset()`, `add()`, or the done endpoint changes the list, and the tests assert these exact strings in the returned HTML. Detail: `specs/002-show-how-many-are-left/spec.html`.

## Item 003: Untick a done to-do

Keep unticking as a dedicated `POST /todos/{todo_id}/undo` route that clears `done` and returns `303` to `/`, returns `404` for an unknown id, and is idempotent for an already-open item, mirroring `/done`; do not replace it with a toggle or checkbox, because repeated Undo submissions must never re-tick a to-do and the page is plain HTML forms with no JavaScript. `item()` must emit the inline Undo form only for done items, leaving open items with exactly one Done form, and both forms must stay real `method="post"` forms with the submit button inside and the exact `action` path, because a missing method submits GET and `data-method="post"` does not count; the tests parse real attributes and require one form per row. Keep the Undo button inline beside the struck-through title with the same styling as the Done button (`form.done, form.undo`), and keep the remaining count server-derived in `render()` from the `done` flags rather than a stored counter so that clearing `done` raises it automatically; keep titles escaped with `html.escape` in both states. Detail: `specs/003-untick-a-done-to-do/spec.html`.
