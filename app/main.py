"""makase-todo: one page of to-dos, served by FastAPI and held in memory."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Annotated

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="makase-todo")


@dataclass
class Todo:
    """One to-do. ``done`` is in the model from the start; no control on the page sets it yet."""

    id: int
    title: str
    done: bool = False


STARTERS = (
    ("Buy milk", True),
    ("Water the plants", False),
    ("Call the dentist", False),
    ("Read a chapter of a book", False),
    ("Take out the recycling", False),
)
"""The to-dos the page opens with, as ``(title, done)``, so a fresh start shows a populated
list with one already done."""

todos: list[Todo] = []
"""Every to-do, in the order added. Nothing survives a restart."""


def reset() -> None:
    """Put the list back to the starters. Runs at import, and before each test."""
    todos.clear()
    for title, done in STARTERS:
        add(title).done = done


def add(title: str) -> Todo:
    """Append a to-do with the next free id."""
    todo = Todo(id=max((one.id for one in todos), default=0) + 1, title=title)
    todos.append(todo)
    return todo


def item(todo: Todo) -> str:
    """One to-do's list item: its escaped title, struck through once it is done."""
    title = html.escape(todo.title)
    if todo.done:
        return f'      <li class="todo done"><s>{title}</s></li>'
    return f'      <li class="todo">{title}</li>'


def render() -> str:
    """The whole page, as one HTML string."""
    items = "\n".join(item(todo) for todo in todos)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>To-dos</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 32rem; margin: 2rem auto; }}
    body {{ padding: 0 1rem; }}
    ul {{ padding-left: 1.2rem; }}
    li {{ margin: 0.3rem 0; }}
    form.add {{ display: flex; gap: 0.5rem; margin-top: 1rem; }}
    form.add input {{ flex: 1; }}
  </style>
</head>
<body>
  <main>
    <h1>To-dos</h1>
    <ul>
{items}
    </ul>
    <form class="add" method="post" action="/todos">
      <input name="title" placeholder="What needs doing?" aria-label="New to-do">
      <button type="submit">Add</button>
    </form>
  </main>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    """The to-do page."""
    return render()


@app.post("/todos")
def create(title: Annotated[str, Form()] = "") -> RedirectResponse:
    """Add a to-do from the form, then send the browser back to the page.

    A blank title is ignored rather than refused, so the page simply reloads unchanged.
    """
    cleaned = title.strip()
    if cleaned:
        add(cleaned)
    return RedirectResponse("/", status_code=303)


reset()
