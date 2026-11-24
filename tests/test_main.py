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


def test_a_title_is_escaped() -> None:
    client.post("/todos", data={"title": "<b>bold</b>"})

    page = client.get("/").text
    assert "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "<b>bold</b>" not in page
