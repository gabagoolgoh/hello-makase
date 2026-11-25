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
    row_forms = forms_in(row)
    assert len(row_forms) == 2
    assert posts_to(row_forms[0], f"/todos/{todo.id}/done")
    assert "<s>" not in row
    assert visible_title_between_forms(row, row_forms[0], row_forms[1]) == todo.title
    assert_edit_link_between_forms(row, row_forms[0], row_forms[1], todo.id)
    box_buttons = buttons_in(row_forms[0])
    assert len(box_buttons) == 1
    box_attributes = button_attributes(box_buttons[0])
    assert box_attributes.get("type") == "submit", "the box must be a submit control"
    assert button_text(box_buttons[0]) == "☐"
    assert box_attributes.get("role") == "checkbox"
    assert box_attributes.get("aria-checked") == "false"
    assert box_attributes.get("aria-label") == todo.title
    assert "Done" not in row
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
    assert todo not in main.todos
    assert todo.id not in [one.id for one in main.todos]
    page_response = client.get("/")
    assert page_response.status_code == 200
    after = page_response.text
    assert html.escape(todo.title) not in after
    assert todo.title not in after
    assert f"/todos/{todo.id}/" not in after, "the deleted to-do should offer no actions"
    assert len(rendered_list_items(after)) == len(main.todos), (
        "the deleted to-do should leave no placeholder row behind"
    )


def rendered_item(page: str, title: str) -> str:
    """The one line of the page rendering the list item for ``title``."""
    return next(line for line in page.splitlines() if html.escape(title) in line)


def rendered_list_items(page: str) -> list[str]:
    """Each whole to-do list item, ``<li>...</li>``, rather than a whole source line."""
    return re.findall(r'<li class="todo[^"]*">.*?</li>', page, re.DOTALL)


def rendered_titles(page: str, todos: list[main.Todo]) -> list[str]:
    """The titles of the rendered to-do rows, in the order the page draws them."""
    rows = rendered_list_items(page)
    titles = []
    for row in rows:
        matches = [one.title for one in todos if html.escape(one.title) in row]
        assert len(matches) == 1, f"each row should render one known title: {row}"
        titles.append(matches[0])
    return titles


def visible_title_between_forms(row: str, box_form: str, delete_form: str) -> str:
    """The title a browser shows between a row's box form and its Delete form.

    HTML comments and tags are dropped before decoding, so a title hidden in a comment, an
    attribute, or the source generally does not count as visible title text. The row's Edit
    link is dropped too, so this returns the title alone rather than the title and Edit.
    """
    start = row.index(box_form) + len(box_form)
    between = row[start : row.index(delete_form, start)]
    without_comments = re.sub(r"<!--.*?-->", "", between, flags=re.DOTALL)
    without_edit = re.sub(r"<a\b[^>]*>.*?</a>", "", without_comments, flags=re.DOTALL)
    return html.unescape(re.sub(r"<[^>]+>", "", without_edit)).strip()


def title_markup_between_forms(row: str, box_form: str, delete_form: str) -> str:
    """The escaped title source between a row's box form and its Delete form.

    Tags and comments are dropped but entities are left as written, so an ampersand or quote
    left raw in the visible title shows up instead of being silently decoded away. The box's
    ``aria-label`` sits inside the box form, so it cannot satisfy this check. The Edit link is
    dropped as well, leaving the title's own markup.
    """
    start = row.index(box_form) + len(box_form)
    between = row[start : row.index(delete_form, start)]
    without_comments = re.sub(r"<!--.*?-->", "", between, flags=re.DOTALL)
    without_edit = re.sub(r"<a\b[^>]*>.*?</a>", "", without_comments, flags=re.DOTALL)
    return re.sub(r"<[^>]+>", "", without_edit).strip()


def remaining_count(page: str) -> str:
    """The text of the page's remaining-count paragraph."""
    match = re.search(r'<p class="remaining">([^<]*)</p>', page)
    assert match is not None, "the page should show its remaining count"
    return match.group(1)


def without_inert_markup(fragment: str) -> str:
    """The fragment as a browser renders it, without comments or template contents."""
    without_comments = re.sub(r"<!--.*?-->", "", fragment, flags=re.DOTALL)
    return re.sub(
        r"<template\b[^>]*>.*?</template>",
        "",
        without_comments,
        flags=re.DOTALL | re.IGNORECASE,
    )


def forms_in(fragment: str) -> list[str]:
    """Each whole live ``<form ...>...</form>`` in a page fragment, with its opening tag.

    A button outside a form is therefore not found, and neither is a form's method lost. A
    form inside a comment or an inert template is not live, so it is not found either.
    """
    return re.findall(
        r"<form\b[^>]*>.*?</form>", without_inert_markup(fragment), re.DOTALL
    )


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


def links_in(fragment: str) -> list[str]:
    """Each whole live ``<a ...>...</a>`` in a page fragment."""
    return re.findall(r"<a\b[^>]*>.*?</a>", without_inert_markup(fragment), re.DOTALL)


def link_attributes(link: str) -> dict[str, str]:
    """The attributes on a link's opening tag, by their real names."""
    opening = link[: link.index(">")]
    pairs = re.findall(
        r'''([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))''',
        opening,
    )
    return {name.lower(): double or single or bare for name, double, single, bare in pairs}


def link_text(link: str) -> str:
    """The visible text of a link, with tags stripped and entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", link)).strip()


def assert_edit_link_between_forms(
    row: str, box_form: str, delete_form: str, todo_id: int
) -> None:
    """A row carries one Edit link to its own edit page between its box and Delete."""
    start = row.index(box_form) + len(box_form)
    between = row[start : row.index(delete_form, start)]
    edit_links = links_in(between)
    assert len(edit_links) == 1, "the row should carry one Edit link between title and Delete"
    attributes = link_attributes(edit_links[0])
    assert attributes.get("href") == f"/?edit={todo_id}"
    assert link_text(edit_links[0]) == "Edit"


def tag_has_attribute(tag: str, name: str) -> bool:
    """Whether a start tag carries an attribute, including a valueless boolean one."""
    opening = tag[: tag.index(">")]
    without_quoted_values = re.sub(r'"[^"]*"|\'[^\']*\'', "", opening)
    return (
        re.search(
            rf"(?<![-:\w]){re.escape(name)}(?=\s|=|/?>)",
            without_quoted_values,
            re.IGNORECASE,
        )
        is not None
    )


def form_submission(form: str, submitter: str) -> tuple[str, str]:
    """The method and target a browser sends when ``submitter`` activates ``form``.

    A submitter's own ``formmethod`` and ``formaction`` override the form's, and a disabled
    submitter cannot submit at all. The method is returned lower-cased.
    """
    assert not tag_has_attribute(submitter, "disabled"), "the box must be enabled to submit"
    form_values = form_attributes(form)
    submitter_values = button_attributes(submitter)
    method = submitter_values.get("formmethod", form_values.get("method", ""))
    action = submitter_values.get("formaction", form_values.get("action", ""))
    return method.lower(), action


def buttons_in(fragment: str) -> list[str]:
    """Each whole live ``<button ...>...</button>`` in a page fragment."""
    return re.findall(
        r"<button\b[^>]*>.*?</button>", without_inert_markup(fragment), re.DOTALL
    )


def input_controls_in(fragment: str) -> list[str]:
    """Each whole live ``<input ...>`` control in a page fragment."""
    return re.findall(r"<input\b[^>]*>", without_inert_markup(fragment), re.IGNORECASE)


def input_label(control: str) -> str:
    """The label a browser shows for a button-type input, decoded."""
    attributes = button_attributes(control)
    if attributes.get("type", "").lower() == "image":
        return html.unescape(attributes.get("alt", "")).strip()
    return html.unescape(attributes.get("value", "")).strip()


def button_attributes(button: str) -> dict[str, str]:
    """The attributes on a button's opening tag, by their real names."""
    opening = button[: button.index(">")]
    pairs = re.findall(
        r'''([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))''',
        opening,
    )
    return {name.lower(): double or single or bare for name, double, single, bare in pairs}


def button_text(button: str) -> str:
    """The visible text of a button, with tags stripped and entities decoded."""
    return html.unescape(re.sub(r"<[^>]+>", "", button)).strip()


def style_rules(page: str) -> list[tuple[str, str]]:
    """Each selector and declaration pair from the page's own <style> block."""
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL)
    assert style is not None, "the page should carry its own styles"
    css = re.sub(r"/\*.*?\*/", "", style.group(1), flags=re.DOTALL)
    rules: list[tuple[str, str]] = []
    for selector_text, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for selector in selector_text.split(","):
            for declaration in body.split(";"):
                name, separator, value = declaration.partition(":")
                if separator:
                    rules.append((selector.strip(), f"{name.strip()}: {value.strip()}"))
    return rules


def text_decorations_on_s(page: str) -> list[str]:
    """The text-decoration values the page's styles give a bare <s> element."""
    values: list[str] = []
    for selector, declaration in style_rules(page):
        final_selector = selector.split()[-1]
        if final_selector not in {"s", "*"}:
            continue
        name, _, value = declaration.partition(":")
        if name.lower() in {"text-decoration", "text-decoration-line"}:
            values.append(value.lower())
    return values


def assert_page_styles_keep_title_struck_through(page: str, row: str, title: str) -> None:
    """The title is in <s> and no page style replaces that strike-through."""
    assert f"<s>{html.escape(title)}</s>" in row, "the done title should be struck through"
    decorations = text_decorations_on_s(page)
    assert not any("line-through" not in value for value in decorations), (
        "the page styles must not replace or cancel the strike-through"
    )


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

    rows = rendered_list_items(page)
    assert len(rows) == len(main.todos), "the page should draw one list item per to-do"
    for todo in main.todos:
        matching_rows = [row for row in rows if html.escape(todo.title) in row]
        assert len(matching_rows) == 1, f"{todo.title} should have exactly one list item"
        row = matching_rows[0]
        row_forms = forms_in(row)
        assert len(row_forms) == 2, f"{todo.title} should offer exactly two actions inside its row"

        first_action = "undo" if todo.done else "done"
        expected_glyph = "&#9745;" if todo.done else "&#9744;"
        expected_checked = "true" if todo.done else "false"
        assert posts_to(row_forms[0], f"/todos/{todo.id}/{first_action}"), (
            f"{todo.title} should act on itself with its {first_action} box"
        )
        box_buttons = buttons_in(row_forms[0])
        assert len(box_buttons) == 1
        box_attributes = button_attributes(box_buttons[0])
        assert expected_glyph in box_buttons[0]
        assert box_attributes.get("type") == "submit", f"{todo.title}'s box must be a submit control"
        assert button_text(box_buttons[0]) == ("☑" if todo.done else "☐"), (
            f"{todo.title}'s box must display its glyph as visible text"
        )
        assert box_attributes.get("role") == "checkbox"
        assert box_attributes.get("aria-checked") == expected_checked
        assert box_attributes.get("aria-label") == todo.title
        assert posts_to(row_forms[1], f"/todos/{todo.id}/delete"), (
            f"{todo.title} should offer Delete after its box"
        )
        assert '<button type="submit">Delete</button>' in row_forms[1]
        assert "Done" not in row, "no row should show a Done button"
        assert "Undo" not in row, "no row should show an Undo button"


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
    assert "<b>bold</b>" not in page
    assert "<s>" not in row, "the reopened row should not be struck through"
    row_forms = forms_in(row)
    assert len(row_forms) == 2
    assert posts_to(row_forms[0], f"/todos/{todo.id}/done")
    box_buttons = buttons_in(row_forms[0])
    assert len(box_buttons) == 1
    box_attributes = button_attributes(box_buttons[0])
    assert box_attributes.get("type") == "submit", "the box must be a submit control"
    assert button_text(box_buttons[0]) == "☐"
    assert box_attributes.get("role") == "checkbox"
    assert box_attributes.get("aria-checked") == "false"
    assert html.unescape(box_attributes.get("aria-label", "")) == todo.title
    assert visible_title_between_forms(row, row_forms[0], row_forms[1]) == todo.title, (
        "the reopened row should show its title as text, not only in the box label"
    )
    assert_edit_link_between_forms(row, row_forms[0], row_forms[1], todo.id)


def test_case_1_an_open_row_starts_with_an_empty_box_posting_done() -> None:
    """Case 1: an open row's only box form posts to /done as an unchecked checkbox."""
    todo = main.add("Wash the car")
    page = client.get("/").text
    row = rendered_item(page, todo.title)

    assert not todo.done
    assert html.escape(todo.title) in row
    row_forms = forms_in(row)
    assert len(row_forms) == 2
    assert posts_to(row_forms[0], f"/todos/{todo.id}/done")
    box_buttons = buttons_in(row_forms[0])
    assert len(box_buttons) == 1, "the box form should hold only the box button"
    box_button = box_buttons[0]
    attributes = button_attributes(box_button)
    assert attributes.get("type") == "submit", "the box must be a submit control"
    assert button_text(box_button) == "☐"
    assert attributes.get("role") == "checkbox"
    assert attributes.get("aria-checked") == "false"
    assert attributes.get("aria-label") == todo.title


def test_case_2_a_done_row_starts_with_a_ticked_box_posting_undo() -> None:
    """Case 2: a done row's only box form posts to /undo as a checked checkbox."""
    todo = main.add("Post the letter")
    todo.done = True
    page = client.get("/").text
    row = rendered_item(page, todo.title)

    assert html.escape(todo.title) in row
    assert f"<s>{html.escape(todo.title)}</s>" in row
    row_forms = forms_in(row)
    assert len(row_forms) == 2
    assert posts_to(row_forms[0], f"/todos/{todo.id}/undo")
    box_buttons = buttons_in(row_forms[0])
    assert len(box_buttons) == 1, "the box form should hold only the box button"
    box_button = box_buttons[0]
    attributes = button_attributes(box_button)
    assert attributes.get("type") == "submit", "the box must be a submit control"
    assert button_text(box_button) == "☑", "the tick must be the box's visible text"
    assert attributes.get("role") == "checkbox"
    assert attributes.get("aria-checked") == "true"
    assert attributes.get("aria-label") == todo.title


def test_case_3_every_row_is_box_then_title_then_delete() -> None:
    """Case 3: each row starts with its live box form, then its title, then its live Delete."""
    page = client.get("/").text
    rows = rendered_list_items(page)
    assert len(rows) == len(main.todos)

    for todo in main.todos:
        matching_rows = [row for row in rows if html.escape(todo.title) in row]
        assert len(matching_rows) == 1
        row = without_inert_markup(matching_rows[0])
        row_forms = forms_in(row)
        assert len(row_forms) == 2, f"{todo.title} should offer exactly two live actions"
        first_action = "undo" if todo.done else "done"
        assert posts_to(row_forms[0], f"/todos/{todo.id}/{first_action}")
        assert posts_to(row_forms[1], f"/todos/{todo.id}/delete")
        assert len(buttons_in(row_forms[0])) == 1, (
            f"{todo.title}'s box form should hold one live box button"
        )

        opening = re.match(r"<li\b[^>]*>", row)
        assert opening is not None, "each row should be a list item"
        body = row[opening.end() : row.rindex("</li>")].strip()
        assert body.startswith(row_forms[0]), (
            "the row should start with its box form, with no visible text before it"
        )
        assert body.endswith(row_forms[1]), (
            "the row should end with its Delete form, with no visible text after it"
        )
        assert visible_title_between_forms(row, row_forms[0], row_forms[1]) == todo.title, (
            "the title should be the visible text between the box and Delete"
        )
        assert_edit_link_between_forms(row, row_forms[0], row_forms[1], todo.id)


def test_case_4_no_row_shows_a_done_or_undo_button() -> None:
    """Case 4: no row has a button or button-type input showing Done or Undo."""
    page = client.get("/").text
    rows = rendered_list_items(page)
    assert rows

    for row in rows:
        for button in buttons_in(row):
            visible_word = button_text(button)
            assert visible_word not in {"Done", "Undo"}
        button_inputs = [
            control
            for control in input_controls_in(row)
            if button_attributes(control).get("type", "").lower()
            in {"button", "submit", "reset", "image"}
        ]
        for control in button_inputs:
            visible_word = input_label(control)
            assert visible_word not in {"Done", "Undo"}, (
                f"a button-type input displaying {visible_word} should not appear in a row"
            )


def test_case_5_clicking_an_open_box_ticks_it_and_drops_the_count() -> None:
    """Case 5: submitting an open row's rendered box answers 303 to /, ticks it, and lowers the count."""
    todo = main.add("Wash the car")
    assert remaining_count(client.get("/").text) == "5 left"
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    row_forms = forms_in(row)
    assert len(row_forms) == 2
    box_form = row_forms[0]
    assert posts_to(box_form, f"/todos/{todo.id}/done")
    box_buttons = buttons_in(box_form)
    assert len(box_buttons) == 1, "the box form should hold only the box button"
    box_button = box_buttons[0]
    assert button_attributes(box_button).get("type") == "submit", (
        "the box must be a submit control"
    )
    method, action = form_submission(box_form, box_button)
    assert method == "post"
    assert action == f"/todos/{todo.id}/done"

    response = client.post(action, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert todo.done
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    assert "&#9745;" in row
    assert f"<s>{html.escape(todo.title)}</s>" in row
    assert remaining_count(page) == "4 left"


def test_case_6_clicking_a_done_box_opens_it_and_raises_the_count() -> None:
    """Case 6: submitting a done row's rendered box answers 303 to /, unticks it, and raises the count."""
    todo = next(one for one in main.todos if one.done)
    assert remaining_count(client.get("/").text) == "4 left"
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    row_forms = forms_in(row)
    assert len(row_forms) == 2
    box_form = row_forms[0]
    assert posts_to(box_form, f"/todos/{todo.id}/undo")
    box_buttons = buttons_in(box_form)
    assert len(box_buttons) == 1, "the box form should hold only the box button"
    box_button = box_buttons[0]
    assert button_attributes(box_button).get("type") == "submit", (
        "the box must be a submit control"
    )
    method, action = form_submission(box_form, box_button)
    assert method == "post"
    assert action == f"/todos/{todo.id}/undo"

    response = client.post(action, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert not todo.done
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    assert "&#9744;" in row
    assert "<s>" not in row, "the reopened row should not be struck through"
    row_forms = forms_in(row)
    assert visible_title_between_forms(row, row_forms[0], row_forms[1]) == todo.title
    assert_edit_link_between_forms(row, row_forms[0], row_forms[1], todo.id)
    assert remaining_count(page) == "5 left"


def test_case_7_posting_the_same_rendered_box_twice_keeps_the_state_it_names() -> None:
    """Case 7: resubmitting a row's rendered box leaves the state that box named."""
    open_todo = main.add("Wash the car")
    done_todo = main.add("Post the letter")
    done_todo.done = True
    page = client.get("/").text

    for todo, path, box_glyph, expected_done, result_glyph in (
        (open_todo, f"/todos/{open_todo.id}/done", "☐", True, "&#9745;"),
        (done_todo, f"/todos/{done_todo.id}/undo", "☑", False, "&#9744;"),
    ):
        row = rendered_item(page, todo.title)
        row_forms = forms_in(row)
        assert len(row_forms) == 2
        box_form = row_forms[0]
        assert posts_to(box_form, path)
        box_buttons = buttons_in(box_form)
        assert len(box_buttons) == 1, "the box form should hold only the box button"
        box_button = box_buttons[0]
        assert button_attributes(box_button).get("type") == "submit", (
            "the box must be a submit control"
        )
        assert button_text(box_button) == box_glyph
        method, action = form_submission(box_form, box_button)
        assert method == "post"
        assert action == path

        for _ in range(2):
            response = client.post(action, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/"

        assert todo.done == expected_done
        result_row = rendered_item(client.get("/").text, todo.title)
        assert result_glyph in result_row
        if expected_done:
            assert f"<s>{html.escape(todo.title)}</s>" in result_row
        else:
            assert "<s>" not in result_row


def test_case_8_each_box_labels_itself_with_the_escaped_title() -> None:
    """Case 8: a title with <, & or " is escaped in the box label and the visible title.

    Both states are checked: the label attribute must survive intact and decode back to the
    title, and the row must show that title as text of its own, apart from the label.
    """
    todo = main.add('<b>bold & "quoted"</b>')

    for done in (False, True):
        todo.done = done
        page = client.get("/").text
        row = rendered_item(page, todo.title)
        row_forms = forms_in(row)
        assert len(row_forms) == 2
        action = "undo" if done else "done"
        assert posts_to(row_forms[0], f"/todos/{todo.id}/{action}")
        box_buttons = buttons_in(row_forms[0])
        assert len(box_buttons) == 1
        attributes = button_attributes(box_buttons[0])
        label = attributes.get("aria-label")
        assert label is not None, "the box should carry the title as its label"
        assert html.unescape(label) == todo.title, (
            "the label attribute should hold the escaped title intact"
        )
        assert html.escape(todo.title) in box_buttons[0]
        assert todo.title not in page, "the raw title must not break the attribute or the text"
        assert title_markup_between_forms(row, row_forms[0], row_forms[1]) == html.escape(
            todo.title
        ), "the row should display the escaped title as text, not only in the box label"
        assert_edit_link_between_forms(row, row_forms[0], row_forms[1], todo.id)


def test_case_9_an_empty_list_shows_no_boxes_and_still_offers_add() -> None:
    """Case 9: an empty list renders no boxes and still offers the Add form."""
    main.todos.clear()

    page = client.get("/").text

    assert rendered_list_items(page) == []
    assert not any(
        button_attributes(button).get("role") == "checkbox" for button in buttons_in(page)
    )
    visible_box_buttons = [
        button
        for button in buttons_in(page)
        if any(glyph in button_text(button) for glyph in ("\u2610", "\u2611"))
    ]
    assert visible_box_buttons == [], (
        "the empty page should show no box button, even one missing its checkbox role"
    )
    input_controls = input_controls_in(page)
    native_checkboxes = [
        control
        for control in input_controls
        if button_attributes(control).get("type", "").lower() == "checkbox"
    ]
    assert native_checkboxes == [], "the empty page should show no native checkbox"
    checkbox_inputs = [
        control
        for control in input_controls
        if button_attributes(control).get("role", "").lower() == "checkbox"
        or "aria-checked" in button_attributes(control)
    ]
    assert checkbox_inputs == [], (
        "the empty page should show no input button claiming checkbox semantics"
    )
    glyph_inputs = [
        control
        for control in input_controls
        if any(glyph in input_label(control) for glyph in ("\u2610", "\u2611"))
    ]
    assert glyph_inputs == [], (
        "the empty page should show no input button displaying a box glyph"
    )
    add_forms = [form for form in forms_in(page) if posts_to(form, "/todos")]
    assert len(add_forms) == 1, "the empty page should still offer its Add form"
    assert '<button type="submit">Add</button>' in add_forms[0]


def test_case_10_a_newly_added_todo_shows_an_empty_box() -> None:
    """Case 10: a to-do added through the Add form renders a usable empty box.

    The box must be a submit control whose visible text is the empty glyph, with checkbox
    semantics, so a glyph tucked into an attribute or a button that cannot submit fails.
    """
    response = client.post("/todos", data={"title": "Fix the bike"}, follow_redirects=False)
    assert response.status_code == 303
    todo = next(one for one in main.todos if one.title == "Fix the bike")

    row = rendered_item(client.get("/").text, todo.title)
    assert remaining_count(client.get("/").text) == "5 left"
    row_forms = forms_in(row)
    assert len(row_forms) == 2
    box_form = row_forms[0]
    assert posts_to(box_form, f"/todos/{todo.id}/done")
    box_buttons = buttons_in(box_form)
    assert len(box_buttons) == 1, "the box form should hold only the box button"
    box_button = box_buttons[0]
    attributes = button_attributes(box_button)
    assert attributes.get("type") == "submit", "the box must be a submit control"
    assert button_text(box_button) == "\u2610", "the empty glyph must be the box's visible text"
    assert attributes.get("role") == "checkbox"
    assert attributes.get("aria-checked") == "false"
    assert html.unescape(attributes.get("aria-label", "")) == todo.title

    method, action = form_submission(box_form, box_button)
    assert method == "post"
    assert action == f"/todos/{todo.id}/done"
    posted = client.post(action, follow_redirects=False)
    assert posted.status_code == 303
    assert posted.headers["location"] == "/"
    assert todo.done
    assert remaining_count(client.get("/").text) == "4 left"


def test_case_2_page_styles_keep_a_done_title_struck_through() -> None:
    """Case 2: the page styles keep a done row's title struck through."""
    todo = next(one for one in main.todos if one.done)
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    assert_page_styles_keep_title_struck_through(page, row, todo.title)


def test_case_5_page_styles_keep_a_newly_done_title_struck_through() -> None:
    """Case 5: the page styles keep a title struck through once its open box is clicked."""
    todo = main.add("Wash the car")
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    box_form = forms_in(row)[0]
    box_buttons = buttons_in(box_form)
    assert len(box_buttons) == 1, "the box form should hold only the box button"
    method, action = form_submission(box_form, box_buttons[0])
    assert method == "post"
    assert action == f"/todos/{todo.id}/done"

    response = client.post(action, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert todo.done
    page = client.get("/").text
    row = rendered_item(page, todo.title)
    assert_page_styles_keep_title_struck_through(page, row, todo.title)


def test_edit_case_1_every_row_links_to_its_edit_form_between_title_and_delete() -> None:
    """Case 1: every open and done row has an Edit link after its title and before Delete."""
    main.add("Post the letter").done = True
    page = client.get("/").text
    assert any(one.done for one in main.todos)
    assert any(not one.done for one in main.todos)

    for todo in main.todos:
        row = rendered_item(page, todo.title)
        row_forms = forms_in(row)
        assert len(row_forms) == 2, f"{todo.title} should still have exactly two forms"
        box_form = row_forms[0]
        delete_form = row_forms[1]
        edit_links = links_in(row)
        assert len(edit_links) == 1, f"{todo.title} should have one Edit link"
        edit_link = edit_links[0]
        assert link_attributes(edit_link).get("href") == f"/?edit={todo.id}"
        assert link_text(edit_link) == "Edit"
        title_start = row.index(html.escape(todo.title), row.index(box_form) + len(box_form))
        assert row.index(edit_link) > title_start, "Edit should follow the title"
        assert row.index(edit_link) < row.index(delete_form), "Edit should precede Delete"


def test_edit_case_2_a_row_opens_as_its_own_edit_form() -> None:
    """Case 2: GET /?edit={id} draws that row as a POST edit form with no box or Delete."""
    todo = main.add("Wash the car")

    response = client.get("/", params={"edit": str(todo.id)})

    assert response.status_code == 200
    page = response.text
    row = rendered_item(page, todo.title)
    row_forms = forms_in(row)
    assert len(row_forms) == 1, "the edited row should hold one form"
    form = row_forms[0]
    assert posts_to(form, f"/todos/{todo.id}/edit")
    title_inputs = [
        control
        for control in input_controls_in(form)
        if button_attributes(control).get("name") == "title"
    ]
    assert len(title_inputs) == 1, "the edit form should hold one title input"
    title_input = title_inputs[0]
    attributes = button_attributes(title_input)
    assert attributes.get("value") == html.escape(todo.title)
    assert attributes.get("aria-label"), "the title input should be labelled for screen readers"
    save_buttons = buttons_in(form)
    assert len(save_buttons) == 1, "the edit form should hold one Save button"
    assert button_attributes(save_buttons[0]).get("type") == "submit"
    assert button_text(save_buttons[0]) == "Save"
    cancel_links = links_in(form)
    assert len(cancel_links) == 1, "the edit form should hold one Cancel link"
    assert link_attributes(cancel_links[0]).get("href") == "/"
    assert link_text(cancel_links[0]) == "Cancel"
    assert not any(
        button_attributes(button).get("role") == "checkbox" for button in buttons_in(row)
    ), "the edited row should show no checkbox"
    assert not any(
        posts_to(candidate, f"/todos/{todo.id}/delete") for candidate in forms_in(row)
    ), "the edited row should show no Delete"
    edit_forms = [
        candidate
        for candidate in forms_in(page)
        if posts_to(candidate, f"/todos/{todo.id}/edit")
    ]
    assert len(edit_forms) == 1, "only one row should be in edit mode"


def test_edit_case_3_every_other_row_is_unchanged_while_one_is_edited() -> None:
    """Case 3: in an edit page every row except the edited one matches plain GET /."""
    target = main.todos[1]
    plain = client.get("/").text
    edit_page = client.get("/", params={"edit": str(target.id)}).text
    plain_rows = rendered_list_items(plain)
    edit_rows = rendered_list_items(edit_page)
    assert len(plain_rows) == len(main.todos)
    assert len(edit_rows) == len(main.todos)

    for todo in main.todos:
        if todo is target:
            continue
        plain_row = next(row for row in plain_rows if html.escape(todo.title) in row)
        edit_row = next(row for row in edit_rows if html.escape(todo.title) in row)
        assert edit_row == plain_row

    target_row = next(row for row in edit_rows if html.escape(target.title) in row)
    target_forms = forms_in(target_row)
    assert len(target_forms) == 1
    assert posts_to(target_forms[0], f"/todos/{target.id}/edit")


def test_edit_case_4_saving_a_new_title_keeps_its_id_and_place() -> None:
    """Case 4: saving a title answers 303 to / and shows the new title in the same position."""
    target = main.todos[2]
    old_title = target.title
    old_id = target.id
    old_index = main.todos.index(target)

    response = client.post(
        f"/todos/{target.id}/edit", data={"title": "New title"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert target.id == old_id
    assert target.title == "New title"
    assert main.todos.index(target) == old_index
    page = client.get("/").text
    assert "New title" in page
    assert old_title not in page
    assert rendered_titles(page, main.todos)[old_index] == "New title"


def test_edit_case_5_saving_keeps_done_state_and_remaining_count() -> None:
    """Case 5: renaming keeps a done to-do struck through and an open one open."""
    done_todo = next(one for one in main.todos if one.done)
    open_todo = next(one for one in main.todos if not one.done)
    before_count = remaining_count(client.get("/").text)

    for todo, new_title in ((done_todo, "Done renamed"), (open_todo, "Open renamed")):
        was_done = todo.done
        response = client.post(
            f"/todos/{todo.id}/edit", data={"title": new_title}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert todo.done == was_done
        page = client.get("/").text
        row = rendered_item(page, new_title)
        if was_done:
            assert f"<s>{html.escape(new_title)}</s>" in row
        else:
            assert "<s>" not in row
        assert remaining_count(page) == before_count


def test_edit_case_6_saving_trims_spaces_around_the_title() -> None:
    """Case 6: saving a title with spaces around it stores it trimmed."""
    target = main.todos[0]

    response = client.post(
        f"/todos/{target.id}/edit", data={"title": "  Trimmed title  "}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert target.title == "Trimmed title"
    page = client.get("/").text
    assert "Trimmed title" in page
    assert "  Trimmed title  " not in page


def test_edit_case_7_a_blank_save_keeps_the_title() -> None:
    """Case 7: a blank or all-spaces save answers 303 to / and leaves the title unchanged."""
    target = main.todos[1]
    original = target.title
    before = [(one.id, one.title, one.done) for one in main.todos]

    for blank in ("", "   ", "\t\n"):
        response = client.post(
            f"/todos/{target.id}/edit", data={"title": blank}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert target.title == original
        assert [(one.id, one.title, one.done) for one in main.todos] == before


def test_edit_case_8_saving_the_same_title_changes_nothing() -> None:
    """Case 8: saving the same title answers 303 to / and changes nothing."""
    target = main.todos[2]
    before = [(one.id, one.title, one.done) for one in main.todos]
    before_page = client.get("/").text

    response = client.post(
        f"/todos/{target.id}/edit", data={"title": target.title}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert [(one.id, one.title, one.done) for one in main.todos] == before
    assert client.get("/").text == before_page


def test_edit_case_9_saving_an_unknown_or_deleted_id_is_404() -> None:
    """Case 9: an id that is not on the list answers 404 and changes no to-do."""
    before = [(one.id, one.title, one.done) for one in main.todos]
    unknown = max(one.id for one in main.todos) + 1

    response = client.post(
        f"/todos/{unknown}/edit", data={"title": "Ghost"}, follow_redirects=False
    )

    assert response.status_code == 404
    assert [(one.id, one.title, one.done) for one in main.todos] == before

    deleted = main.add("Delete me")
    client.post(f"/todos/{deleted.id}/delete", follow_redirects=False)
    after_delete = [(one.id, one.title, one.done) for one in main.todos]

    response = client.post(
        f"/todos/{deleted.id}/edit", data={"title": "Ghost"}, follow_redirects=False
    )

    assert response.status_code == 404
    assert [(one.id, one.title, one.done) for one in main.todos] == after_delete


def test_edit_case_10_a_non_integer_edit_id_is_422() -> None:
    """Case 10: /todos/not-an-int/edit is refused and leaves the to-dos unchanged."""
    before = [(one.id, one.title, one.done) for one in main.todos]

    response = client.post("/todos/not-an-int/edit", data={"title": "Nope"}, follow_redirects=False)

    assert response.status_code == 422
    assert [(one.id, one.title, one.done) for one in main.todos] == before


def test_edit_case_11_a_bad_edit_value_draws_the_normal_page() -> None:
    """Case 11: an unknown, deleted or non-integer edit value draws the normal page."""
    never_existed = max(one.id for one in main.todos) + 100
    deleted = main.add("Delete me")
    client.post(f"/todos/{deleted.id}/delete", follow_redirects=False)

    def assert_bad_edit_draws_normal_page(value: str) -> None:
        plain = client.get("/")
        response = client.get("/", params={"edit": value})
        assert response.status_code == 200
        assert response.text == plain.text
        assert not any(
            "/edit" in form_attributes(form).get("action", "")
            for form in forms_in(response.text)
        ), "the normal page should show no row in edit mode"

    assert_bad_edit_draws_normal_page(str(never_existed))
    assert_bad_edit_draws_normal_page(str(deleted.id))
    assert_bad_edit_draws_normal_page("not-an-int")
    assert_bad_edit_draws_normal_page("")


def test_edit_case_12_an_escaped_title_stays_escaped_in_the_input_and_saved_row() -> None:
    """Case 12: <, & and " stay escaped in the edit input and after saving."""
    title = '<b>bold & "quoted"</b>'
    todo = main.add(title)

    response = client.get("/", params={"edit": str(todo.id)})

    assert response.status_code == 200
    page = response.text
    row = rendered_item(page, title)
    form = forms_in(row)[0]
    title_input = next(
        control
        for control in input_controls_in(form)
        if button_attributes(control).get("name") == "title"
    )
    attributes = button_attributes(title_input)
    assert attributes.get("value") == html.escape(title)
    assert attributes.get("aria-label"), "the title input should be labelled"
    assert title not in page, "the raw title must not break the input attribute"

    new_title = '<i>saved & "quoted"</i>'
    saved = client.post(
        f"/todos/{todo.id}/edit", data={"title": new_title}, follow_redirects=False
    )

    assert saved.status_code == 303
    assert saved.headers["location"] == "/"
    page = client.get("/").text
    row = rendered_item(page, new_title)
    assert html.escape(new_title) in row
    assert new_title not in page
    box_form = forms_in(row)[0]
    box_buttons = buttons_in(box_form)
    assert len(box_buttons) == 1
    label = button_attributes(box_buttons[0]).get("aria-label")
    assert label is not None
    assert label == html.escape(new_title)
    assert html.unescape(label) == new_title


def test_edit_case_13_saving_one_title_leaves_every_other_unchanged() -> None:
    """Case 13: saving one title leaves every other id, title, done flag and order unchanged."""
    target = main.todos[2]
    old_id = target.id
    others = [(one.id, one.title, one.done) for one in main.todos if one is not target]
    before_order = [one.id for one in main.todos]

    response = client.post(
        f"/todos/{target.id}/edit", data={"title": "Only this one"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert target.id == old_id
    assert target.title == "Only this one"
    assert [(one.id, one.title, one.done) for one in main.todos if one is not target] == others
    assert [one.id for one in main.todos] == before_order
    page = client.get("/").text
    assert rendered_titles(page, main.todos) == [one.title for one in main.todos]
