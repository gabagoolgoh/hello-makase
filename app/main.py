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
            "</button></form>"
        )
        return (
            f'      <li class="todo done">{box} <span class="title"><s>{title}</s></span> '
            f"{edit} {delete}</li>"
        )
    box = (
        f'<form class="done" method="post" action="/todos/{todo.id}/done">'
        f'<button type="submit" role="checkbox" aria-checked="false" aria-label="{title}">'
        "</button></form>"
    )
    return (
        f'      <li class="todo">{box} <span class="title">{title}</span> '
        f"{edit} {delete}</li>"
    )


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
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 8px 12px; font-family: system-ui, sans-serif; font-size: 13px; background: #f4f4f2; color: #18181b; }}
    main {{ max-width: 32rem; margin: 0 auto; padding: 8px 12px; background: #ffffff; border: 1px solid #e4e4e7; border-radius: 8px; }}
    .head {{ display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 4px; }}
    h1 {{ margin: 0; font-size: 1.1rem; }}
    p.remaining {{ margin: 0; font-size: 11px; color: #71717a; }}
    ul {{ list-style: none; padding: 0; margin: 0 0 8px; }}
    li {{ display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px solid #f4f4f5; }}
    .title {{ flex: 1; min-width: 0; overflow-wrap: anywhere; }}
    li.done .title {{ color: #a1a1aa; }}
    form.done, form.undo {{ display: flex; flex-shrink: 0; margin: 0; }}
    form.done button, form.undo button {{ position: relative; width: 15px; height: 15px; padding: 0; background: #ffffff; border: 1.5px solid #a1a1aa; border-radius: 4px; cursor: pointer; flex-shrink: 0; }}
    form.undo button {{ background: #2563eb; border-color: #2563eb; }}
    form.undo button::after {{ content: ""; position: absolute; left: 4px; top: 1px; width: 4px; height: 8px; border: solid #ffffff; border-width: 0 2px 2px 0; transform: rotate(45deg); }}
    a.edit, form.delete button {{ padding: 1px 6px; font: inherit; font-size: 11px; color: #71717a; background: transparent; border: none; border-radius: 4px; text-decoration: none; cursor: pointer; flex-shrink: 0; }}
    form.delete {{ display: flex; margin: 0; }}
    form.edit {{ display: flex; flex: 1; align-items: center; gap: 6px; min-width: 0; margin: 0; }}
    form.edit input {{ flex: 1; min-width: 0; padding: 4px 8px; font: inherit; background: #fafafa; border: 1px solid #d4d4d8; border-radius: 5px; }}
    form.edit button {{ padding: 1px 6px; font: inherit; font-size: 11px; color: #18181b; background: #fafafa; border: 1px solid #d4d4d8; border-radius: 4px; cursor: pointer; }}
    form.add {{ display: flex; gap: 6px; }}
    form.add input {{ flex: 1; min-width: 0; padding: 4px 8px; font: inherit; background: #fafafa; border: 1px solid #d4d4d8; border-radius: 5px; }}
    form.add button {{ padding: 4px 10px; font: inherit; font-weight: 500; color: #ffffff; background: #2563eb; border: none; border-radius: 5px; cursor: pointer; }}
  </style>
</head>
<body>
  <main>
    <div class="head">
      <h1>To-dos</h1>
      <p class="remaining">{count}</p>
    </div>
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
