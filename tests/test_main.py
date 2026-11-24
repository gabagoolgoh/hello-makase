import html
import re
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


def test_undoing_a_done_todo_returns_it_to_open() -> None:
    """Case 1: Undo answers 303 to /, clears ``done``, and the page shows it open again."""
    todo = main.add("Wash the car")
    todo.done = True

    response = client.post(f"/todos/{todo.id}/undo", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert not todo.done
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    assert html.escape(todo.title) in row
    assert "<s>" not in row
    assert '<button type="submit">Done</button>' in row
    assert "Undo" not in row


def test_undoing_raises_the_remaining_count_by_one() -> None:
    """Case 2: unticking a done starter takes the page from 4 left to 5 left."""
    done = next(one for one in main.todos if one.done)
    assert remaining_count(client.get("/").text) == "4 left"

    client.post(f"/todos/{done.id}/undo", follow_redirects=False)

    assert remaining_count(client.get("/").text) == "5 left"


def test_undoing_the_last_done_todo_leaves_one_left() -> None:
    """Case 3: from Nothing left, unticking one to-do says 1 left."""
    for todo in main.todos:
        todo.done = True
    target = main.todos[0]
    assert remaining_count(client.get("/").text) == "Nothing left"

    client.post(f"/todos/{target.id}/undo", follow_redirects=False)

    assert remaining_count(client.get("/").text) == "1 left"


def test_done_and_undo_round_trip() -> None:
    """Case 4: done, undo, then done again returns the to-do to done."""
    todo = main.add("Post the letter")

    client.post(f"/todos/{todo.id}/done", follow_redirects=False)
    assert todo.done

    client.post(f"/todos/{todo.id}/undo", follow_redirects=False)
    assert not todo.done

    client.post(f"/todos/{todo.id}/done", follow_redirects=False)
    assert todo.done
    assert f'action="/todos/{todo.id}/undo"' in client.get("/").text


def test_undoing_an_open_todo_is_idempotent() -> None:
    """Case 6: undoing a to-do that is already open changes nothing else."""
    target = main.todos[1]
    assert not target.done
    before = [(one.id, one.title, one.done) for one in main.todos]
    before_page = client.get("/").text

    response = client.post(f"/todos/{target.id}/undo", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert not target.done
    assert [(one.id, one.title, one.done) for one in main.todos] == before
    assert client.get("/").text == before_page


def rendered_item(page: str, title: str) -> str:
    """The one line of the page rendering the list item for ``title``."""
    return next(line for line in page.splitlines() if html.escape(title) in line)


def remaining_count(page: str) -> str:
    """The text of the page's remaining-count paragraph."""
    match = re.search(r'<p class="remaining">([^<]*)</p>', page)
    assert match is not None, "the page should show its remaining count"
    return match.group(1)


def forms_in(fragment: str) -> list[str]:
    """Each whole ``<form ...>...</form>`` in a page fragment, with its opening tag.

    A button outside a form is therefore not found, and neither is a form's method lost.
    """
    return re.findall(r"<form\b[^>]*>.*?</form>", fragment, re.DOTALL)


def posts_to(form: str, path: str) -> bool:
    """Whether ``form`` posts to ``path``. A form with no method submits with GET."""
    opening = form[: form.index(">")]
    method = re.search(r'\bmethod\s*=\s*["\']?(\w+)', opening, re.IGNORECASE)
    action = re.search(r'\baction\s*=\s*["\']([^"\']*)["\']', opening, re.IGNORECASE)
    return (
        method is not None
        and method.group(1).lower() == "post"
        and action is not None
        and action.group(1) == path
    )


def test_a_done_todo_shows_undo_and_an_open_one_does_not() -> None:
    """Case 5: done items render an Undo form; open items render only their Done form."""
    done = next(one for one in main.todos if one.done)
    open_todo = next(one for one in main.todos if not one.done)
    page = client.get("/").text

    done_forms = forms_in(rendered_item(page, done.title))
    assert len(done_forms) == 1, "a done to-do should offer exactly one action, Undo"
    assert posts_to(done_forms[0], f"/todos/{done.id}/undo")
    assert '<button type="submit">Undo</button>' in done_forms[0]

    open_forms = forms_in(rendered_item(page, open_todo.title))
    assert len(open_forms) == 1, "an open to-do should offer exactly one action, Done"
    assert posts_to(open_forms[0], f"/todos/{open_todo.id}/done")
    assert '<button type="submit">Done</button>' in open_forms[0]
    assert "Undo" not in open_forms[0]


def test_undoing_an_unknown_todo_is_404() -> None:
    """Case 7: an unknown id is 404 and changes nothing, including when the list is empty."""
    before = [(one.id, one.title, one.done) for one in main.todos]
    before_count = remaining_count(client.get("/").text)
    unknown = max(one.id for one in main.todos) + 1

    response = client.post(f"/todos/{unknown}/undo", follow_redirects=False)

    assert response.status_code == 404
    assert [(one.id, one.title, one.done) for one in main.todos] == before
    assert remaining_count(client.get("/").text) == before_count

    main.todos.clear()
    empty_count = remaining_count(client.get("/").text)
    response = client.post("/todos/1/undo", follow_redirects=False)
    assert response.status_code == 404
    assert main.todos == []
    assert remaining_count(client.get("/").text) == empty_count


def test_a_non_integer_undo_id_is_422() -> None:
    """Case 8: /todos/not-an-int/undo is refused and leaves the to-dos unchanged."""
    before = [(one.id, one.title, one.done) for one in main.todos]

    response = client.post("/todos/not-an-int/undo", follow_redirects=False)

    assert response.status_code == 422
    assert [(one.id, one.title, one.done) for one in main.todos] == before


def test_unticking_a_title_keeps_it_escaped() -> None:
    """Case 9: a title with HTML characters stays escaped after Undo."""
    todo = main.add("<b>bold</b>")
    todo.done = True

    client.post(f"/todos/{todo.id}/undo", follow_redirects=False)

    page = client.get("/").text
    assert "&lt;b&gt;bold&lt;/b&gt;" in page
    assert "<b>bold</b>" not in page
