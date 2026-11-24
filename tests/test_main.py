from collections.abc import Iterator

import pytest
from app import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh_list() -> Iterator[None]:
    main.reset()
    yield


def test_the_page_lists_the_seeded_todos() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert main.todos, "the page should open with some to-dos already on it"
    for todo in main.todos:
        assert todo.title in response.text


def test_adding_a_todo_shows_it_on_the_page() -> None:
    response = client.post("/todos", data={"title": "Fix the bike"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "Fix the bike" in client.get("/").text


def test_a_blank_title_is_ignored() -> None:
    before = client.get("/").text

    response = client.post("/todos", data={"title": "   "}, follow_redirects=False)

    assert response.status_code == 303
    assert client.get("/").text == before


def test_a_done_todo_is_drawn_differently() -> None:
    todo = main.add("Post the letter")
    not_done = client.get("/").text

    todo.done = True
    done = client.get("/").text

    assert "Post the letter" in not_done
    assert "Post the letter" in done
    assert done != not_done


def test_the_page_counts_the_todos_that_are_not_done() -> None:
    page = client.get("/").text

    assert "4 left" in page


def test_adding_a_todo_raises_the_count_by_one() -> None:
    before = client.get("/").text

    client.post("/todos", data={"title": "Fix the bike"})

    after = client.get("/").text
    assert "4 left" in before
    assert "5 left" in after


def test_one_left_when_only_one_todo_is_not_done() -> None:
    for todo in main.todos:
        todo.done = todo.title != "Water the plants"

    assert "1 left" in client.get("/").text


def test_nothing_left_when_every_todo_is_done() -> None:
    for todo in main.todos:
        todo.done = True

    assert "Nothing left" in client.get("/").text


def test_a_title_is_escaped() -> None:
    client.post("/todos", data={"title": "<b>bold</b>"})

    page = client.get("/").text
    assert "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "<b>bold</b>" not in page


def test_marking_a_todo_done_strikes_it_through() -> None:
    todo = main.add("Wash the car")

    response = client.post(f"/todos/{todo.id}/done", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert todo.done
    assert main.item(todo) in client.get("/").text


def test_an_unknown_todo_is_404() -> None:
    before = [one.done for one in main.todos]
    unknown = max(one.id for one in main.todos) + 1

    response = client.post(f"/todos/{unknown}/done", follow_redirects=False)

    assert response.status_code == 404
    assert [one.done for one in main.todos] == before
