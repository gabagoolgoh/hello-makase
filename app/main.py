"""makase-todo: one page of to-dos, served by FastAPI and held in memory."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="makase-todo")


@dataclass
class Todo:
    """One to-do. The *Done* button beside it sets ``done``."""

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
    """One to-do's list item: its escaped title, struck through with an *Undo* button beside it
    once it is done, and a *Done* button beside it until then."""
    title = html.escape(todo.title)
    if todo.done:
        undo = (
            f'<form class="undo" method="post" action="/todos/{todo.id}/undo">'
            '<button type="submit">Undo</button></form>'
        )
        return f'      <li class="todo done"><s>{title}</s> {undo}</li>'
    done = (
        f'<form class="done" method="post" action="/todos/{todo.id}/done">'
        '<button type="submit">Done</button></form>'
    )
    return f'      <li class="todo">{title} {done}</li>'


def render() -> str:
    """The whole page, as one HTML string."""
    items = "\n".join(item(todo) for todo in todos)
    left = sum(1 for todo in todos if not todo.done)
    count = "Nothing left" if left == 0 else f"{left} left"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>To-dos</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 32rem; margin: 0.6rem auto; padding: 0 1rem; background: #ffffff; color: #000000; font-size: 14px; }}
    h1 {{ font-size: 1.35rem; margin: 0 0 0.25rem; }}
    p.remaining {{ margin: 0 0 0.45rem; }}
    ul {{ padding-left: 1.2rem; margin: 0.25rem 0; }}
    li {{ margin: 0.25rem 0; }}
    form.add {{ display: flex; gap: 0.5rem; margin-top: 0.55rem; }}
    form.add input {{ flex: 1; min-width: 0; }}
    form.done, form.undo {{ display: inline; margin-left: 0.5rem; }}
  </style>
</head>
<body>
  <main>
    <h1>To-dos</h1>
    <p class="remaining">{count}</p>
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


@app.post("/todos/{todo_id}/done")
def mark_done(todo_id: int) -> RedirectResponse:
    """Mark one to-do done, then send the browser back to the page. An unknown id is 404."""
    todo = next((one for one in todos if one.id == todo_id), None)
    if todo is None:
        raise HTTPException(status_code=404, detail="There is no such to-do.")
    todo.done = True
    return RedirectResponse("/", status_code=303)


@app.post("/todos/{todo_id}/undo")
def mark_undone(todo_id: int) -> RedirectResponse:
    """Mark one to-do not done, then send the browser back to the page. An unknown id is 404."""
    todo = next((one for one in todos if one.id == todo_id), None)
    if todo is None:
        raise HTTPException(status_code=404, detail="There is no such to-do.")
    todo.done = False
    return RedirectResponse("/", status_code=303)


reset()
