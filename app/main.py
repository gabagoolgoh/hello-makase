"""makase-todo: an in-memory to-do list with a JSON API and a built JS front end."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

app = FastAPI(title="makase-todo")

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


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


class TodoOut(BaseModel):
    """One to-do as the JSON API serves it, with its title left exactly as stored."""

    id: int
    title: str
    done: bool


class TodoListOut(BaseModel):
    """The whole list, in order, and how many are still open."""

    todos: list[TodoOut]
    remaining: int


class TodoIn(BaseModel):
    """A new to-do's title, trimmed, so a blank title is refused with 422."""

    title: str

    @field_validator("title")
    @classmethod
    def trimmed(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A title cannot be blank.")
        return cleaned


class TodoPatch(BaseModel):
    """The fields a PATCH may change, either or both, absent when not sent.

    A ``title`` that arrives is trimmed the same way an Add's is, so a blank one is 422.
    """

    title: str | None = None
    done: bool | None = None

    @field_validator("title")
    @classmethod
    def trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A title cannot be blank.")
        return cleaned


def find(todo_id: int) -> Todo:
    """The to-do with that id, or a JSON 404 when it is not on the list."""
    todo = next((one for one in todos if one.id == todo_id), None)
    if todo is None:
        raise HTTPException(status_code=404, detail="There is no such to-do.")
    return todo


@app.get("/api/todos", response_model=TodoListOut)
def api_list() -> TodoListOut:
    """Every to-do in the order added, and how many are still open."""
    return TodoListOut(
        todos=[TodoOut(id=one.id, title=one.title, done=one.done) for one in todos],
        remaining=sum(1 for one in todos if not one.done),
    )


@app.post("/api/todos", status_code=201, response_model=TodoOut)
def api_create(body: TodoIn) -> TodoOut:
    """Add a to-do from the JSON title, which the model already trimmed, and answer 201."""
    todo = add(body.title)
    return TodoOut(id=todo.id, title=todo.title, done=todo.done)


@app.patch("/api/todos/{todo_id}", response_model=TodoOut)
def api_update(todo_id: int, body: TodoPatch) -> TodoOut:
    """Change one to-do's title and/or done flag. An unknown id is a JSON 404; a blank
    title is a 422 that leaves the to-do as it was."""
    todo = find(todo_id)
    if body.title is not None:
        todo.title = body.title
    if body.done is not None:
        todo.done = body.done
    return TodoOut(id=todo.id, title=todo.title, done=todo.done)


@app.delete("/api/todos/{todo_id}", status_code=204)
def api_delete(todo_id: int) -> Response:
    """Remove one to-do from the live list, answering 204. An unknown id is a JSON 404."""
    todo = find(todo_id)
    try:
        todos.remove(todo)
    except ValueError:  # another Delete removed it between the lookup and the removal
        raise HTTPException(status_code=404, detail="There is no such to-do.") from None
    return Response(status_code=204)


app.mount("/", StaticFiles(directory=DIST, html=True, check_dir=False), name="frontend")

reset()
