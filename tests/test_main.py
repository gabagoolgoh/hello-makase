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


def test_deleting_an_open_todo_removes_it_and_drops_the_count() -> None:
    """Case 1: deleting an open to-do answers 303 to /, hides it, and lowers the count."""
    todo = main.add("Walk the dog")
    assert remaining_count(client.get("/").text) == "5 left"

    response = client.post(f"/todos/{todo.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    page = client.get("/").text
    assert todo.id not in [one.id for one in main.todos]
    assert todo.title not in page
    assert remaining_count(page) == "4 left"


def test_deleting_a_done_todo_removes_it_without_changing_the_count() -> None:
    """Case 2: deleting a done to-do answers 303 to / and leaves the count unchanged."""
    todo = main.add("Post the letter")
    todo.done = True
    assert remaining_count(client.get("/").text) == "4 left"

    response = client.post(f"/todos/{todo.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    page = client.get("/").text
    assert todo.id not in [one.id for one in main.todos]
    assert todo.title not in page
    assert remaining_count(page) == "4 left"


def test_deleting_one_todo_leaves_every_other_unchanged() -> None:
    """Case 3: deleting one to-do preserves every other id, title, done flag and order."""
    target = main.todos[1]
    others = [(one.id, one.title, one.done) for one in main.todos if one is not target]
    before_titles = rendered_titles(client.get("/").text, main.todos)
    assert before_titles == [one.title for one in main.todos], (
        "the page should draw the to-dos in the order they were added"
    )

    response = client.post(f"/todos/{target.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert [(one.id, one.title, one.done) for one in main.todos] == others
    after_titles = rendered_titles(client.get("/").text, main.todos)
    assert after_titles == [title for _, title, _ in others], (
        "the returned page should keep the same row order, with only the target gone"
    )
    assert after_titles == [title for title in before_titles if title != target.title]


def test_overlapping_deletes_leave_both_deleted_todos_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cases 3 and 5: a Delete must not restore what another Delete removed meanwhile."""
    first = main.todos[1]
    second = main.todos[3]
    others = [
        (one.id, one.title, one.done) for one in main.todos if one is not first and one is not second
    ]

    class OverlappingDeletes(list[main.Todo]):
        trigger = True

        def __iter__(self) -> Iterator[main.Todo]:
            snapshot = list.copy(self)
            if self.trigger:
                self.trigger = False
                assert main.delete(second.id).status_code == 303
            return iter(snapshot)

    monkeypatch.setattr(main, "todos", OverlappingDeletes(main.todos))

    response = client.post(f"/todos/{first.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert first.id not in [one.id for one in main.todos]
    assert second.id not in [one.id for one in main.todos]
    assert [(one.id, one.title, one.done) for one in main.todos] == others


def test_a_missing_delete_does_not_discard_an_overlapping_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 5: deleting an absent id must not overwrite an Add that lands meanwhile."""
    missing = max(one.id for one in main.todos) + 1
    added: list[main.Todo] = []

    class AddDuringIteration(list[main.Todo]):
        trigger = True

        def __iter__(self) -> Iterator[main.Todo]:
            snapshot = list.copy(self)
            if self.trigger:
                self.trigger = False
                added.append(main.add("Added during Delete"))
            return iter(snapshot)

    monkeypatch.setattr(main, "todos", AddDuringIteration(main.todos))

    response = client.post(f"/todos/{missing}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert added, "the overlapping Add should have happened"
    new_todo = added[0]
    assert new_todo in main.todos
    assert new_todo.title in client.get("/").text


def test_overlapping_adds_get_distinct_ids_and_delete_one_keeps_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 7: overlapping Adds reserve distinct ids, so deleting one keeps the other."""
    real_todo = main.Todo
    overlapping: list[main.Todo] = []

    class TodoThatAddsAnother(real_todo):  # type: ignore[misc]
        trigger = True

        def __init__(self, id: int, title: str, done: bool = False) -> None:
            if type(self).trigger:
                type(self).trigger = False
                overlapping.append(main.add("Added during Add"))
            super().__init__(id=id, title=title, done=done)

    monkeypatch.setattr(main, "Todo", TodoThatAddsAnother)

    first = main.add("First")

    assert overlapping, "the overlapping Add should have happened"
    second = overlapping[0]
    assert first.id != second.id, "overlapping Adds must not share a counter value"
    assert first in main.todos
    assert second in main.todos
    page = client.get("/").text
    assert first.title in page
    assert second.title in page

    response = client.post(f"/todos/{first.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert first not in main.todos
    assert second in main.todos
    assert second.title in client.get("/").text


def test_a_missing_or_repeated_delete_answers_303_and_changes_nothing() -> None:
    """Case 5: an absent id, and deleting one to-do twice, both redirect and change nothing."""
    before = [(one.id, one.title, one.done) for one in main.todos]
    unknown = max(one.id for one in main.todos) + 1

    response = client.post(f"/todos/{unknown}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert [(one.id, one.title, one.done) for one in main.todos] == before

    target = main.todos[0]
    first = client.post(f"/todos/{target.id}/delete", follow_redirects=False)
    assert first.status_code == 303
    after_first = [(one.id, one.title, one.done) for one in main.todos]
    assert target.id not in [one.id for one in main.todos]

    second = client.post(f"/todos/{target.id}/delete", follow_redirects=False)

    assert second.status_code == 303
    assert second.headers["location"] == "/"
    assert [(one.id, one.title, one.done) for one in main.todos] == after_first


def test_deleting_every_todo_leaves_an_empty_page_with_the_add_form() -> None:
    """Case 6: deleting every to-do leaves the page rendering with Nothing left and Add."""
    for todo in list(main.todos):
        response = client.post(f"/todos/{todo.id}/delete", follow_redirects=False)
        assert response.status_code == 303

    assert main.todos == []
    response = client.get("/")
    assert response.status_code == 200
    page = response.text
    assert not re.search(r"<li\b", page), "the empty page should list no to-do rows"
    assert remaining_count(page) == "Nothing left"
    add_forms = [form for form in forms_in(page) if posts_to(form, "/todos")]
    assert len(add_forms) == 1, "the empty page should still offer its Add form"
    assert '<input name="title"' in add_forms[0]
    assert '<button type="submit">Add</button>' in add_forms[0]


def test_a_new_todo_gets_an_unused_id_after_the_newest_is_deleted() -> None:
    """Case 7: a deleted id is never reused, so a stale Delete cannot hit the new to-do."""
    used_ids = {one.id for one in main.todos}
    newest = max(main.todos, key=lambda one: one.id)

    response = client.post(f"/todos/{newest.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    client.post("/todos", data={"title": "Another thing"})
    new_todo = next(one for one in main.todos if one.title == "Another thing")

    assert new_todo.id not in used_ids, "a new to-do must not reuse a deleted id"

    stale = client.post(f"/todos/{newest.id}/delete", follow_redirects=False)

    assert stale.status_code == 303
    assert new_todo in main.todos
    assert new_todo.title in client.get("/").text


def test_reset_numbers_the_starters_one_to_five() -> None:
    """Case 8: reset() puts the starters back with ids 1 to 5."""
    main.add("Temporary")

    main.reset()

    assert [one.id for one in main.todos] == [1, 2, 3, 4, 5]


def test_a_non_integer_delete_id_is_422() -> None:
    """Case 9: /todos/not-an-int/delete is refused and leaves the to-dos unchanged."""
    before = [(one.id, one.title, one.done) for one in main.todos]

    response = client.post("/todos/not-an-int/delete", follow_redirects=False)

    assert response.status_code == 422
    assert [(one.id, one.title, one.done) for one in main.todos] == before


def test_done_and_undo_on_a_deleted_id_are_still_404() -> None:
    """Case 10: after a Delete, Done and Undo on that id still answer 404."""
    todo = main.add("Recycle the box")

    deleted = client.post(f"/todos/{todo.id}/delete", follow_redirects=False)
    assert deleted.status_code == 303

    done = client.post(f"/todos/{todo.id}/done", follow_redirects=False)
    undo = client.post(f"/todos/{todo.id}/undo", follow_redirects=False)

    assert done.status_code == 404
    assert undo.status_code == 404
    assert todo.id not in [one.id for one in main.todos]


def test_deleting_an_html_title_removes_its_escaped_row() -> None:
    """Case 11: an HTML title stays escaped beside Delete, and Delete removes it."""
    client.post("/todos", data={"title": "<b>bold</b>"})
    todo = next(one for one in main.todos if one.title == "<b>bold</b>")
    page = client.get("/").text
    row = rendered_item(page, todo.title)

    assert html.escape(todo.title) in row
    assert todo.title not in page
    delete_form = forms_in(row)[1]
    assert posts_to(delete_form, f"/todos/{todo.id}/delete")
    assert '<button type="submit">Delete</button>' in delete_form

    response = client.post(f"/todos/{todo.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    after = client.get("/").text
    assert html.escape(todo.title) not in after
    assert todo.title not in after


def rendered_item(page: str, title: str) -> str:
    """The one line of the page rendering the list item for ``title``."""
    return next(line for line in page.splitlines() if html.escape(title) in line)


def rendered_titles(page: str, todos: list[main.Todo]) -> list[str]:
    """The titles of the rendered to-do rows, in the order the page draws them."""
    rows = re.findall(r'<li class="todo[^"]*">.*?</li>', page, re.DOTALL)
    titles = []
    for row in rows:
        matches = [one.title for one in todos if html.escape(one.title) in row]
        assert len(matches) == 1, f"each row should render one known title: {row}"
        titles.append(matches[0])
    return titles


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


def form_attributes(form: str) -> dict[str, str]:
    """The attributes on a form's opening tag, by their real names.

    Parsing name/value pairs means ``data-method="post"`` is the attribute ``data-method``,
    not the attribute ``method``.
    """
    opening = form[: form.index(">")]
    pairs = re.findall(
        r'''([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))''',
        opening,
    )
    return {name.lower(): double or single or bare for name, double, single, bare in pairs}


def posts_to(form: str, path: str) -> bool:
    """Whether ``form`` really posts to ``path``. A form with no method submits with GET."""
    attributes = form_attributes(form)
    return attributes.get("method", "").lower() == "post" and attributes.get("action") == path


def test_a_done_todo_shows_undo_and_an_open_one_does_not() -> None:
    """Spec 003 case 5 and spec 004 case 4: every row renders its own two actions.

    A done row renders Undo then Delete; an open row renders Done then Delete. Every row of
    a list holding several to-dos in each state is checked, not just the first of each.
    """
    main.add("Post the letter").done = True
    main.add("Wash the car").done = True
    page = client.get("/").text

    done_todos = [one for one in main.todos if one.done]
    open_todos = [one for one in main.todos if not one.done]
    assert len(done_todos) > 1, "the list should hold several done to-dos"
    assert len(open_todos) > 1, "the list should hold several open to-dos"

    for todo in main.todos:
        row = rendered_item(page, todo.title)
        row_forms = forms_in(row)
        assert len(row_forms) == 2, f"{todo.title} should offer exactly two actions"

        first_action = "undo" if todo.done else "done"
        first_button = "Undo" if todo.done else "Done"
        assert posts_to(row_forms[0], f"/todos/{todo.id}/{first_action}"), (
            f"{todo.title} should act on itself with {first_button}"
        )
        assert f'<button type="submit">{first_button}</button>' in row_forms[0]
        assert posts_to(row_forms[1], f"/todos/{todo.id}/delete"), (
            f"{todo.title} should offer Delete after {first_button}"
        )
        assert '<button type="submit">Delete</button>' in row_forms[1]
        assert ("Undo" in row) is todo.done, "only a done row should offer Undo"


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
    """Case 9: Undo reopens the item and its open row still shows the escaped title."""
    todo = main.add("<b>bold</b>")
    todo.done = True

    response = client.post(f"/todos/{todo.id}/undo", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert not todo.done, "Undo should reopen the to-do, not leave it done"
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    assert html.escape(todo.title) in row
    assert "<b>bold</b>" not in page
    assert "<s>" not in row, "the reopened row should not be struck through"
    assert '<button type="submit">Done</button>' in row
