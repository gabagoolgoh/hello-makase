"""makase-todo: one page of to-dos, served by FastAPI and held in memory."""

from __future__ import annotations

import html
from dataclasses import dataclass
from itertools import count
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

next_id = count(1)
"""The ids still to hand out. Each Add takes one before doing anything else, so two Adds
that overlap never read the same number, and a deleted id is never reused."""


def reset() -> None:
    """Put the list back to the starters. Runs at import, and before each test."""
    global next_id
    todos.clear()
    next_id = count(1)
    for title, done in STARTERS:
        add(title).done = done


def add(title: str) -> Todo:
    """Append a to-do with the next id reserved from the counter."""
    todo = Todo(id=next(next_id), title=title)
    todos.append(todo)
    return todo


def item(todo: Todo) -> str:
    """One to-do's list item: a box that sets its state, its escaped title struck through
    once it is done, an *Edit* link after the title, and a *Delete* button after either
    one. The box is the row's Done or Undo form, drawn as an empty or ticked checkbox and
    labelled with the title."""
    title = html.escape(todo.title)
    edit = f'<a class="edit" href="/?edit={todo.id}">Edit</a>'
    delete = (
        f'<form class="delete" method="post" action="/todos/{todo.id}/delete">'
        '<button type="submit">Delete</button></form>'
    )
    if todo.done:
        box = (
            f'<form class="undo" method="post" action="/todos/{todo.id}/undo">'
            f'<button type="submit" role="checkbox" aria-checked="true" aria-label="{title}">'
            "&#9745;</button></form>"
        )
        return f'      <li class="todo done">{box} <s>{title}</s> {edit} {delete}</li>'
    box = (
        f'<form class="done" method="post" action="/todos/{todo.id}/done">'
        f'<button type="submit" role="checkbox" aria-checked="false" aria-label="{title}">'
        "&#9744;</button></form>"
    )
    return f'      <li class="todo">{box} {title} {edit} {delete}</li>'


def edit_item(todo: Todo) -> str:
    """One to-do's row while it is being edited: a form holding its title and Save/Cancel."""
    title = html.escape(todo.title)
    return (
        f'      <li class="todo editing">'
        f'<form class="edit" method="post" action="/todos/{todo.id}/edit">'
        f'<input name="title" value="{title}" aria-label="Edit title">'
        '<button type="submit">Save</button>'
        '<a href="/">Cancel</a>'
        "</form></li>"
    )


def render(edit_id: int | None = None) -> str:
    """The whole page, as one HTML string. ``edit_id`` draws that row as an edit form."""
    items = "\n".join(
        edit_item(todo) if todo.id == edit_id else item(todo) for todo in todos
    )
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
    form.done, form.undo {{ display: inline; margin-right: 0.4rem; }}
    form.done button, form.undo button {{ padding: 0 0.2rem; border: 1px solid currentColor; border-radius: 0.15rem; background: #ffffff; color: inherit; font: inherit; line-height: 1.2; cursor: pointer; }}
    form.delete {{ display: inline; margin-left: 0.5rem; }}
    a.edit, form.edit {{ display: inline; margin-left: 0.5rem; }}
    form.edit input {{ width: 12rem; }}
    form.edit a {{ margin-left: 0.5rem; }}
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
def page(edit: str | None = None) -> str:
    """The to-do page. ``edit`` opens that row's editor when it names a to-do."""
    edit_id: int | None = None
    if edit is not None:
        try:
            edit_id = int(edit)
        except ValueError:
            edit_id = None
    return render(edit_id)


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


@app.post("/todos/{todo_id}/delete")
def delete(todo_id: int) -> RedirectResponse:
    """Remove one to-do, then send the browser back to the page.

    An id that is not on the list is already gone, so it also redirects rather than 404s.
    The live list is edited in place, so another request's Add or Delete is not overwritten.
    """
    todo = next((one for one in todos if one.id == todo_id), None)
    if todo is not None:
        try:
            todos.remove(todo)
        except ValueError:  # another Delete removed it between the lookup and the removal
            pass
    return RedirectResponse("/", status_code=303)


@app.post("/todos/{todo_id}/edit")
def edit_title(todo_id: int, title: Annotated[str, Form()] = "") -> RedirectResponse:
    """Replace one to-do's title with the trimmed form value, then send the browser back.

    A blank title is ignored rather than refused, like Add. An unknown id is 404.
    """
    todo = next((one for one in todos if one.id == todo_id), None)
    if todo is None:
        raise HTTPException(status_code=404, detail="There is no such to-do.")
    cleaned = title.strip()
    if cleaned:
        todo.title = cleaned
    return RedirectResponse("/", status_code=303)


reset()
