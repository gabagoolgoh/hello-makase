"""The JSON API over the same in-memory to-do list the page uses."""

from collections.abc import Iterator

import pytest
from app import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh_list() -> Iterator[None]:
    main.reset()
    yield


def snapshot() -> list[tuple[int, str, bool]]:
    return [(todo.id, todo.title, todo.done) for todo in main.todos]


def listed() -> dict:
    response = client.get("/api/todos")
    assert response.status_code == 200
    return response.json()


def test_the_api_lists_the_starters_in_order() -> None:
    """Case 1: a fresh app serves the five starters, in order, with remaining: 4."""
    body = listed()

    assert [todo["title"] for todo in body["todos"]] == [
        title for title, _ in main.STARTERS
    ]
    assert [todo["done"] for todo in body["todos"]] == [
        done for _, done in main.STARTERS
    ]
    ids = [todo["id"] for todo in body["todos"]]
    assert ids == sorted(ids), "the API should preserve insertion order"
    assert len(set(ids)) == len(ids)
    assert body["remaining"] == 4


def test_the_api_lists_an_empty_list() -> None:
    """Case 2: nothing on the list means no to-dos and nothing remaining."""
    main.todos.clear()

    assert listed() == {"todos": [], "remaining": 0}


def test_adding_a_todo_through_the_api() -> None:
    """Case 3: a JSON add trims its title, answers 201, and shows up on the next GET."""
    used_ids = {todo["id"] for todo in listed()["todos"]}

    response = client.post("/api/todos", json={"title": "  Fix the bike  "})

    assert response.status_code == 201
    created = response.json()
    assert created["title"] == "Fix the bike"
    assert created["done"] is False
    assert created["id"] not in used_ids

    body = listed()
    assert created in body["todos"]
    assert body["remaining"] == 5


def test_a_blank_title_is_refused_with_422() -> None:
    """Case 4: an empty or whitespace-only title is a JSON error and adds nothing."""
    before = snapshot()

    for blank in ("", "   "):
        response = client.post("/api/todos", json={"title": blank})

        assert response.status_code == 422
        assert "detail" in response.json()
        assert snapshot() == before


def test_a_missing_or_invalid_body_is_refused_with_422() -> None:
    """Case 5: no title field and unparseable JSON are both JSON errors, adding nothing."""
    before = snapshot()

    missing = client.post("/api/todos", json={"not_a_title": "Fix the bike"})
    invalid = client.post(
        "/api/todos",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    for response in (missing, invalid):
        assert response.status_code == 422
        assert "detail" in response.json()
    assert snapshot() == before


def test_patching_done_marks_an_open_todo_done() -> None:
    """Case 6: setting done true answers 200 and lowers remaining by one."""
    target = next(todo for todo in main.todos if not todo.done)
    assert listed()["remaining"] == 4

    response = client.patch(f"/api/todos/{target.id}", json={"done": True})

    assert response.status_code == 200
    assert response.json() == {"id": target.id, "title": target.title, "done": True}
    assert listed()["remaining"] == 3


def test_patching_done_false_undoes_a_done_todo() -> None:
    """Case 7: clearing done answers 200 and raises remaining by one."""
    target = next(todo for todo in main.todos if todo.done)
    assert listed()["remaining"] == 4

    response = client.patch(f"/api/todos/{target.id}", json={"done": False})

    assert response.status_code == 200
    assert response.json() == {"id": target.id, "title": target.title, "done": False}
    assert listed()["remaining"] == 5


def test_repeating_a_done_flag_is_idempotent() -> None:
    """Case 8: the same flag on an item already in that state changes nothing else."""
    done = next(todo for todo in main.todos if todo.done)
    open_todo = next(todo for todo in main.todos if not todo.done)

    for target, flag in ((done, True), (open_todo, False)):
        before = snapshot()
        response = client.patch(f"/api/todos/{target.id}", json={"done": flag})

        assert response.status_code == 200
        assert response.json()["done"] is flag
        assert snapshot() == before


def test_patching_the_title_keeps_it_raw() -> None:
    """Case 9: a new title is trimmed and returned unescaped, with id and done kept."""
    target = main.todos[1]
    before_done = target.done

    response = client.patch(
        f"/api/todos/{target.id}", json={"title": "  <b>New title</b>  "}
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": target.id,
        "title": "<b>New title</b>",
        "done": before_done,
    }
    assert listed()["todos"][1]["title"] == "<b>New title</b>"


def test_a_blank_new_title_is_refused_with_422() -> None:
    """Case 10: a blank title is a JSON error and the old title survives."""
    target = main.todos[1]
    old_title = target.title

    for blank in ("", "   "):
        response = client.patch(f"/api/todos/{target.id}", json={"title": blank})

        assert response.status_code == 422
        assert "detail" in response.json()
        assert target.title == old_title


def test_patching_an_unknown_todo_is_404() -> None:
    """Case 11: an id that is not on the list is a JSON 404 and changes nothing."""
    before = snapshot()
    unknown = max(todo.id for todo in main.todos) + 1

    response = client.patch(f"/api/todos/{unknown}", json={"done": True})

    assert response.status_code == 404
    assert "detail" in response.json()
    assert snapshot() == before


def test_deleting_a_todo_through_the_api() -> None:
    """Case 12: a delete answers 204 empty-handed, drops the item, and never reuses its id."""
    target = main.todos[1]
    others = [one for one in snapshot() if one[0] != target.id]
    used_ids = {todo.id for todo in main.todos}

    response = client.delete(f"/api/todos/{target.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert target.id not in [todo["id"] for todo in listed()["todos"]]
    assert snapshot() == others

    created = client.post("/api/todos", json={"title": "Another thing"}).json()
    assert created["id"] not in used_ids, "a new to-do must not reuse a deleted id"


def test_a_missing_or_repeated_delete_is_404() -> None:
    """Case 13: an unknown id, and deleting the same id twice, are JSON 404s."""
    before = snapshot()
    unknown = max(todo.id for todo in main.todos) + 1

    missing = client.delete(f"/api/todos/{unknown}")

    assert missing.status_code == 404
    assert "detail" in missing.json()
    assert snapshot() == before

    target = main.todos[0]
    assert client.delete(f"/api/todos/{target.id}").status_code == 204
    after_first = snapshot()

    repeated = client.delete(f"/api/todos/{target.id}")

    assert repeated.status_code == 404
    assert "detail" in repeated.json()
    assert snapshot() == after_first


def test_the_api_works_over_the_shared_in_memory_list() -> None:
    """Case 14: the API reads and writes the same in-memory list the app holds."""
    assert [todo["id"] for todo in listed()["todos"]] == [todo.id for todo in main.todos]

    created = client.post("/api/todos", json={"title": "Fix the chain"}).json()
    assert next(todo for todo in main.todos if todo.id == created["id"]).title == (
        "Fix the chain"
    )

    client.patch(f"/api/todos/{created['id']}", json={"done": True})
    assert next(todo for todo in main.todos if todo.id == created["id"]).done is True

    assert client.delete(f"/api/todos/{created['id']}").status_code == 204
    assert created["id"] not in [todo.id for todo in main.todos]


def test_clearing_done_todos_removes_only_them() -> None:
    """Case 1: clearing answers 204 empty, drops every done item, and keeps open items and remaining."""
    open_before = [one for one in snapshot() if not one[2]]
    done_ids = [one[0] for one in snapshot() if one[2]]
    assert done_ids, "the starters should include a done to-do"
    remaining_before = listed()["remaining"]

    response = client.delete("/api/todos/done")

    assert response.status_code == 204
    assert response.content == b""
    assert snapshot() == open_before
    assert [todo["id"] for todo in listed()["todos"]] == [one[0] for one in open_before]
    assert listed()["remaining"] == remaining_before


def test_clearing_done_when_nothing_is_done_changes_nothing() -> None:
    """Case 2: an all-open list and an empty list both answer 204 and stay as they were."""
    for todo in main.todos:
        todo.done = False
    before = snapshot()
    remaining_before = listed()["remaining"]

    response = client.delete("/api/todos/done")

    assert response.status_code == 204
    assert response.content == b""
    assert snapshot() == before
    assert listed()["remaining"] == remaining_before

    main.todos.clear()
    empty = client.delete("/api/todos/done")

    assert empty.status_code == 204
    assert empty.content == b""
    assert listed() == {"todos": [], "remaining": 0}


def test_clearing_done_twice_is_idempotent() -> None:
    """Case 3: a second clear answers 204 and changes nothing."""
    first = client.delete("/api/todos/done")
    assert first.status_code == 204
    after_first = snapshot()

    second = client.delete("/api/todos/done")

    assert second.status_code == 204
    assert second.content == b""
    assert snapshot() == after_first


def test_a_todo_added_after_clearing_never_reuses_a_cleared_id() -> None:
    """Case 4: the ids of cleared done items are not handed out again."""
    cleared = {todo.id for todo in main.todos if todo.done}
    assert cleared, "the starters should include a done to-do"

    assert client.delete("/api/todos/done").status_code == 204

    created = client.post("/api/todos", json={"title": "Fresh start"}).json()

    assert created["id"] not in cleared
