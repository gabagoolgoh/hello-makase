import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { createApp } from "../src/app.js";

const flush = async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
};

function response(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body;
    },
  };
}

function setup({ todos, handler } = {}) {
  const dom = new JSDOM(
    '<!doctype html><html><body><main id="app"></main></body></html>',
    { url: "http://localhost/" },
  );
  const document = dom.window.document;
  const state = (todos ?? [
    { id: 1, title: "Buy milk", done: true },
    { id: 2, title: "Water the plants", done: false },
    { id: 3, title: "Call the dentist", done: false },
  ]).map((todo) => ({ ...todo }));
  const calls = [];
  const fetch = async (url, options = {}) => {
    const method = (options.method ?? "GET").toUpperCase();
    const body = options.body === undefined ? undefined : JSON.parse(options.body);
    calls.push({ url, method, body });
    if (handler) {
      const custom = await handler({ url, method, body, calls, state });
      if (custom) return custom;
    }
    if (url === "/api/todos" && method === "GET") {
      return response(200, {
        todos: state,
        remaining: state.filter((todo) => !todo.done).length,
      });
    }
    if (url === "/api/todos" && method === "POST") {
      const created = {
        id: Math.max(0, ...state.map((todo) => todo.id)) + 1,
        title: body.title,
        done: false,
      };
      return response(201, created);
    }
    if (url === "/api/todos/done" && method === "DELETE") {
      for (let index = state.length - 1; index >= 0; index -= 1) {
        if (state[index].done) state.splice(index, 1);
      }
      return response(204, null);
    }
    const match = url.match(/^\/api\/todos\/(\d+)$/);
    if (match) {
      const id = Number(match[1]);
      const todo = state.find((one) => one.id === id);
      if (method === "PATCH") {
        Object.assign(todo, body);
        return response(200, todo);
      }
      if (method === "DELETE") {
        state.splice(state.indexOf(todo), 1);
        return response(204, null);
      }
    }
    return response(500, { detail: "unexpected request" });
  };

  async function start() {
    const app = createApp({ document, fetch });
    await app.start();
    return { app, calls, document, state };
  }

  return { calls, document, start, state };
}

function rows(document) {
  return [...document.querySelectorAll("li.todo")];
}

function titles(document) {
  return rows(document).map((row) => row.querySelector(".title")?.textContent ?? "");
}

function rowFor(document, title) {
  return rows(document).find((row) => row.textContent.includes(title));
}

function rowById(document, id) {
  return document.querySelector(`li[data-id="${id}"]`);
}

function remaining(document) {
  return document.querySelector(".remaining").textContent;
}

function submit(form) {
  form.dispatchEvent(
    new form.ownerDocument.defaultView.Event("submit", {
      bubbles: true,
      cancelable: true,
    }),
  );
}

function pressKey(input, key, init = {}) {
  input.dispatchEvent(
    new input.ownerDocument.defaultView.KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
      ...init,
    }),
  );
}

function openEditor(document, id) {
  rowById(document, id).querySelector(".edit").click();
  return rowById(document, id).querySelector("form.edit");
}

test("case 4: startup lists every returned todo and the remaining count", async () => {
  const open = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
      { id: 3, title: "Call the dentist", done: false },
    ],
  });
  const started = await open.start();

  assert.deepEqual(
    started.calls.map((call) => call.method),
    ["GET"],
    "startup should make one GET request",
  );
  assert.equal(started.calls[0].url, "/api/todos");
  assert.deepEqual(titles(started.document), [
    "Buy milk",
    "Water the plants",
    "Call the dentist",
  ]);
  assert.equal(remaining(started.document), "2 left");

  const finished = setup({ todos: [{ id: 1, title: "Buy milk", done: true }] });
  const allDone = await finished.start();
  assert.equal(remaining(allDone.document), "Nothing left");
});

test("case 5: adding a non-blank title posts it, appends it, and clears the input", async () => {
  const env = setup();
  const { document, calls } = await env.start();
  const input = document.querySelector('form.add input[name="title"]');

  input.value = "  Fix the bike  ";
  submit(document.querySelector("form.add"));
  await flush();

  const post = calls.find((call) => call.method === "POST");
  assert.ok(post, "adding should POST to the API");
  assert.equal(post.url, "/api/todos");
  assert.deepEqual(post.body, { title: "Fix the bike" });
  assert.ok(titles(document).includes("Fix the bike"), "the returned todo should be shown");
  assert.equal(input.value, "");
  assert.equal(remaining(document), "3 left");
});

test("case 6: a blank or whitespace-only title is not created", async () => {
  const env = setup();
  const { document, calls } = await env.start();
  const input = document.querySelector('form.add input[name="title"]');
  const before = titles(document);

  for (const blank of ("", "   ")) {
    input.value = blank;
    submit(document.querySelector("form.add"));
    await flush();
  }

  assert.equal(calls.filter((call) => call.method === "POST").length, 0);
  assert.deepEqual(titles(document), before);
});

test("case 7: toggling sends the opposite done flag and updates row and count", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Open job", done: false },
      { id: 2, title: "Done job", done: true },
    ],
  });
  const { document, calls } = await env.start();

  rowFor(document, "Open job").querySelector(".toggle").click();
  await flush();

  const firstPatch = calls.find((call) => call.method === "PATCH");
  assert.equal(firstPatch.url, "/api/todos/1");
  assert.deepEqual(firstPatch.body, { done: true });
  assert.ok(rowFor(document, "Open job").classList.contains("done"));
  assert.equal(remaining(document), "Nothing left");

  rowFor(document, "Done job").querySelector(".toggle").click();
  await flush();

  const patches = calls.filter((call) => call.method === "PATCH");
  assert.equal(patches.length, 2);
  assert.equal(patches[1].url, "/api/todos/2");
  assert.deepEqual(patches[1].body, { done: false });
  assert.ok(!rowFor(document, "Done job").classList.contains("done"));
  assert.equal(remaining(document), "1 left");
});

test("case 8: edit prefills, cancel sends nothing, save patches, and blank save is refused", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Wash the car", done: false },
      { id: 2, title: "Post the letter", done: true },
    ],
  });
  const { document, calls, state } = await env.start();

  rowFor(document, "Wash the car").querySelector(".edit").click();
  const firstForm = rowById(document, 1).querySelector("form.edit");
  assert.ok(firstForm, "Edit should open an inline form");
  assert.equal(firstForm.querySelector('input[name="title"]').value, "Wash the car");

  firstForm.querySelector(".cancel").click();
  await flush();
  assert.equal(document.querySelector("form.edit"), null, "Cancel should close the editor");
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);

  rowFor(document, "Wash the car").querySelector(".edit").click();
  const saveForm = rowById(document, 1).querySelector("form.edit");
  saveForm.querySelector('input[name="title"]').value = "  Washed the car  ";
  submit(saveForm);
  await flush();

  const patch = calls.find((call) => call.method === "PATCH");
  assert.equal(patch.url, "/api/todos/1");
  assert.deepEqual(patch.body, { title: "Washed the car" });
  assert.ok(titles(document).includes("Washed the car"));
  assert.equal(document.querySelector("form.edit"), null);

  rowFor(document, "Washed the car").querySelector(".edit").click();
  const blankForm = rowById(document, 1).querySelector("form.edit");
  const beforePatches = calls.filter((call) => call.method === "PATCH").length;
  blankForm.querySelector('input[name="title"]').value = "   ";
  submit(blankForm);
  await flush();

  assert.equal(calls.filter((call) => call.method === "PATCH").length, beforePatches);
  assert.equal(state.find((todo) => todo.id === 1).title, "Washed the car");
});

test("case 9: delete removes the row and updates the remaining count", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Keep open", done: false },
      { id: 2, title: "Delete me", done: false },
      { id: 3, title: "Done job", done: true },
    ],
  });
  const { document, calls, state } = await env.start();

  rowFor(document, "Delete me").querySelector(".delete").click();
  await flush();

  const deletion = calls.find((call) => call.method === "DELETE");
  assert.equal(deletion.url, "/api/todos/2");
  assert.ok(!titles(document).includes("Delete me"));
  assert.deepEqual(
    state.map((todo) => todo.id),
    [1, 3],
  );
  assert.equal(remaining(document), "1 left");
});

test("case 10: a title containing HTML renders as literal text", async () => {
  const env = setup({ todos: [{ id: 1, title: "<b>bold</b>", done: false }] });
  const { document } = await env.start();

  const row = rowFor(document, "<b>bold</b>");
  assert.ok(row, "the title should be visible as text");
  assert.equal(row.querySelector(".title").textContent, "<b>bold</b>");
  assert.equal(row.querySelector(".title b"), null);
  assert.equal(document.querySelector("b"), null);
});

test("case 11: an API error shows a message and keeps the rest of the list", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Keep me", done: false },
      { id: 2, title: "Also keep me", done: true },
    ],
    handler: async ({ method }) => {
      if (method === "DELETE") return response(404, { detail: "There is no such to-do." });
      if (method === "POST") return response(422, { detail: "A title cannot be blank." });
      return null;
    },
  });
  const { document } = await env.start();
  const before = titles(document);

  rowFor(document, "Keep me").querySelector(".delete").click();
  await flush();

  const error = document.querySelector(".error");
  assert.equal(error.hidden, false, "the error should be visible");
  assert.ok(error.textContent.trim(), "the error should say what went wrong");
  assert.deepEqual(titles(document), before, "a failed delete should not clear the list");

  const input = document.querySelector('form.add input[name="title"]');
  input.value = "Will fail";
  submit(document.querySelector("form.add"));
  await flush();

  assert.equal(document.querySelector(".error").hidden, false);
  assert.deepEqual(titles(document), before, "a failed add should not change the list");
});

test("case 1: Escape closes the editor, keeps the original title, and sends no PATCH", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();
  const form = openEditor(document, 1);
  const input = form.querySelector('input[name="title"]');
  input.value = "Oat milk";

  pressKey(input, "Escape");
  await flush();

  assert.equal(document.querySelector("form.edit"), null, "Escape should close the editor");
  assert.equal(rowById(document, 1).querySelector(".title").textContent, "Buy milk");
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);
});

test("case 2: Escape closes the editor when the input is empty or whitespace", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();

  for (const value of ["", "   "]) {
    const form = openEditor(document, 1);
    const input = form.querySelector('input[name="title"]');
    input.value = value;
    pressKey(input, "Escape");
    await flush();

    assert.equal(
      document.querySelector("form.edit"),
      null,
      `Escape should close the editor for ${JSON.stringify(value)}`,
    );
    assert.equal(rowById(document, 1).querySelector(".title").textContent, "Buy milk");
  }

  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);
});

test("case 3: Escape closes an unchanged editor and renders the normal row", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();
  const form = openEditor(document, 1);

  pressKey(form.querySelector('input[name="title"]'), "Escape");
  await flush();

  const row = rowById(document, 1);
  assert.equal(row.querySelector("form.edit"), null);
  assert.ok(row.querySelector(".edit"), "the Edit button should be back");
  assert.ok(row.querySelector(".toggle"), "the done toggle should be back");
  assert.ok(row.querySelector(".delete"), "the Delete button should be back");
  assert.equal(row.querySelector(".title").textContent, "Buy milk");
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);
});

test("case 4: Escape after a failed save closes the editor and clears the error", async () => {
  const env = setup({
    todos: [{ id: 1, title: "Buy milk", done: false }],
    handler: async ({ method }) => {
      if (method === "PATCH") return response(500, { detail: "Could not save the title." });
      return null;
    },
  });
  const { document, state } = await env.start();
  const form = openEditor(document, 1);
  const input = form.querySelector('input[name="title"]');
  input.value = "Oat milk";
  submit(form);
  await flush();

  const error = document.querySelector(".error");
  assert.equal(error.hidden, false, "the failed save should show an error");
  assert.equal(error.textContent, "Could not save the title.");

  pressKey(input, "Escape");
  await flush();

  assert.equal(document.querySelector("form.edit"), null, "Escape should close the editor");
  assert.equal(rowById(document, 1).querySelector(".title").textContent, "Buy milk");
  assert.equal(state[0].title, "Buy milk", "the failed save should not change the stored title");
  assert.equal(error.hidden, true, "Escape should clear the error");
  assert.equal(error.textContent, "");
});

test("case 5: Escape during IME composition leaves the editor open", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();
  const form = openEditor(document, 1);
  const input = form.querySelector('input[name="title"]');
  input.value = "Oat milk";

  pressKey(input, "Escape", { isComposing: true });
  await flush();

  assert.equal(document.querySelector("form.edit"), form, "composition Escape should keep the editor open");
  assert.equal(rowById(document, 1).querySelector('input[name="title"]').value, "Oat milk");
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);
});

test("case 6: other keys do not cancel the edit and normal submission still works", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();
  const form = openEditor(document, 1);
  const input = form.querySelector('input[name="title"]');

  pressKey(input, "a");
  pressKey(input, "Enter");
  await flush();

  assert.equal(document.querySelector("form.edit"), form, "other keys should not cancel the edit");
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);

  input.value = "Oat milk";
  submit(form);
  await flush();

  const patch = calls.find((call) => call.method === "PATCH");
  assert.equal(patch.url, "/api/todos/1");
  assert.deepEqual(patch.body, { title: "Oat milk" });
  assert.equal(document.querySelector("form.edit"), null);
});

test("case 7: Escape with no inline editor does nothing", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();
  const before = titles(document);
  const input = document.querySelector('form.add input[name="title"]');
  input.focus();

  pressKey(input, "Escape");
  await flush();

  assert.deepEqual(titles(document), before);
  assert.equal(document.querySelector("form.edit"), null);
  assert.equal(document.querySelector(".error").hidden, true);
  assert.deepEqual(calls.map((call) => call.method), ["GET"]);
});

test("case 8: reopening Edit after Escape pre-fills the original title", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();
  const form = openEditor(document, 1);
  const input = form.querySelector('input[name="title"]');
  input.value = "Discarded change";

  pressKey(input, "Escape");
  await flush();
  assert.equal(document.querySelector("form.edit"), null);

  const reopened = openEditor(document, 1);
  assert.equal(reopened.querySelector('input[name="title"]').value, "Buy milk");
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);
});

test("row case 1: clicking an open to-do's title ticks it and updates row and count", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Open job", done: false },
      { id: 2, title: "Done job", done: true },
    ],
  });
  const { document, calls } = await env.start();

  rowFor(document, "Open job").querySelector(".title").click();
  await flush();

  const patches = calls.filter((call) => call.method === "PATCH");
  assert.equal(patches.length, 1);
  assert.equal(patches[0].url, "/api/todos/1");
  assert.deepEqual(patches[0].body, { done: true });
  const row = rowFor(document, "Open job");
  assert.ok(row.classList.contains("done"));
  assert.ok(row.querySelector(".title s"), "the title should be struck through");
  assert.equal(remaining(document), "Nothing left");
});

test("row case 2: clicking a done row's empty space unticks it and updates row and count", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Open job", done: false },
      { id: 2, title: "Done job", done: true },
    ],
  });
  const { document, calls } = await env.start();
  assert.equal(remaining(document), "1 left");

  rowById(document, 2).click();
  await flush();

  const patches = calls.filter((call) => call.method === "PATCH");
  assert.equal(patches.length, 1);
  assert.equal(patches[0].url, "/api/todos/2");
  assert.deepEqual(patches[0].body, { done: false });
  const row = rowById(document, 2);
  assert.ok(!row.classList.contains("done"));
  assert.equal(row.querySelector(".title s"), null);
  assert.equal(remaining(document), "2 left");
});

test("row case 3: clicking the checkbox sends exactly one PATCH", async () => {
  const env = setup({ todos: [{ id: 1, title: "Open job", done: false }] });
  const { document, calls } = await env.start();

  rowById(document, 1).querySelector(".toggle").click();
  await flush();

  const patches = calls.filter((call) => call.method === "PATCH");
  assert.equal(patches.length, 1);
  assert.deepEqual(patches[0].body, { done: true });
  assert.ok(rowById(document, 1).classList.contains("done"));
});

test("row case 4: clicking Edit opens the editor and sends no PATCH", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();

  rowById(document, 1).querySelector(".edit").click();
  await flush();

  assert.ok(rowById(document, 1).querySelector("form.edit"));
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);
});

test("row case 5: clicking Delete sends only DELETE and no PATCH", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();

  rowById(document, 1).querySelector(".delete").click();
  await flush();

  assert.equal(calls.filter((call) => call.method === "DELETE").length, 1);
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);
  assert.equal(rowById(document, 1), null);
});

test("row case 6: clicks in an editing row never toggle and Save and Cancel still work", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();
  const form = openEditor(document, 1);
  const input = form.querySelector('input[name="title"]');
  const togglePatches = () =>
    calls.filter((call) => call.method === "PATCH" && call.body && "done" in call.body).length;

  input.click();
  rowById(document, 1).click();
  await flush();
  assert.equal(togglePatches(), 0);
  assert.ok(
    rowById(document, 1).querySelector("form.edit"),
    "clicks in the editing row should keep it open",
  );

  form.querySelector(".cancel").click();
  await flush();
  assert.equal(document.querySelector("form.edit"), null);
  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);

  const saveForm = openEditor(document, 1);
  saveForm.querySelector('input[name="title"]').value = "Oat milk";
  submit(saveForm);
  await flush();

  const patches = calls.filter((call) => call.method === "PATCH");
  assert.equal(patches.length, 1);
  assert.deepEqual(patches[0].body, { title: "Oat milk" });
  assert.equal(rowById(document, 1).querySelector(".title").textContent, "Oat milk");
});

test("row case 7: a click that ends with text selected in the row sends no request", async () => {
  const env = setup({ todos: [{ id: 1, title: "Buy milk", done: false }] });
  const { document, calls } = await env.start();
  const title = rowById(document, 1).querySelector(".title");
  const selection = document.defaultView.getSelection();
  const range = document.createRange();
  range.selectNodeContents(title);
  selection.removeAllRanges();
  selection.addRange(range);
  assert.equal(selection.toString(), "Buy milk");

  title.click();
  await flush();

  assert.equal(calls.filter((call) => call.method === "PATCH").length, 0);
  assert.ok(!rowById(document, 1).classList.contains("done"));
  assert.equal(remaining(document), "1 left");
});

test("row case 8: two clicks on the same drawn row send the same done value", async () => {
  let releasePatches;
  const patchesReady = new Promise((resolve) => {
    releasePatches = resolve;
  });
  const env = setup({
    todos: [{ id: 1, title: "Open job", done: false }],
    handler: async ({ url, method, body, state }) => {
      if (method !== "PATCH") return null;
      await patchesReady;
      const id = Number(url.split("/").pop());
      const todo = state.find((one) => one.id === id);
      Object.assign(todo, body);
      return response(200, todo);
    },
  });
  const { document, calls } = await env.start();
  const title = rowById(document, 1).querySelector(".title");

  title.click();
  title.click();
  await flush();

  const patches = calls.filter((call) => call.method === "PATCH");
  assert.equal(patches.length, 2);
  assert.deepEqual(
    patches.map((call) => call.body),
    [{ done: true }, { done: true }],
  );

  releasePatches();
  await flush();
  assert.ok(rowById(document, 1).classList.contains("done"));
});

test("row case 9: a failed row click shows the detail and leaves row and count unchanged", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Open job", done: false },
      { id: 2, title: "Done job", done: true },
    ],
    handler: async ({ method }) => {
      if (method === "PATCH") return response(500, { detail: "Could not change the to-do." });
      return null;
    },
  });
  const { document, calls } = await env.start();
  const before = remaining(document);

  rowById(document, 1).querySelector(".title").click();
  await flush();

  assert.equal(calls.filter((call) => call.method === "PATCH").length, 1);
  const error = document.querySelector(".error");
  assert.equal(error.hidden, false);
  assert.equal(error.textContent, "Could not change the to-do.");
  assert.ok(!rowById(document, 1).classList.contains("done"));
  assert.equal(remaining(document), before);
});

test("row case 10: an HTML title stays literal in a row ticked by a row click", async () => {
  const env = setup({ todos: [{ id: 1, title: "<b>bold</b>", done: false }] });
  const { document, calls } = await env.start();

  rowById(document, 1).querySelector(".title").click();
  await flush();

  assert.equal(calls.filter((call) => call.method === "PATCH").length, 1);
  const row = rowById(document, 1);
  assert.ok(row.classList.contains("done"));
  assert.equal(row.querySelector(".title").textContent, "<b>bold</b>");
  assert.equal(row.querySelector(".title b"), null);
  assert.equal(document.querySelector("b"), null);
});

function filterButton(document, label) {
  return [...document.querySelectorAll(".filters button")].find(
    (button) => button.textContent === label,
  );
}

function selectedFilter(document) {
  return [...document.querySelectorAll(".filters button")].find(
    (button) => button.getAttribute("aria-pressed") === "true",
  )?.textContent;
}

test("filter case 1: All is selected initially, every todo is shown, and the count is open", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
      { id: 3, title: "Call the dentist", done: false },
    ],
  });
  const { document, calls } = await env.start();

  assert.equal(selectedFilter(document), "All");
  assert.equal(filterButton(document, "All").getAttribute("aria-pressed"), "true");
  assert.equal(filterButton(document, "Active").getAttribute("aria-pressed"), "false");
  assert.equal(filterButton(document, "Done").getAttribute("aria-pressed"), "false");
  assert.deepEqual(titles(document), [
    "Buy milk",
    "Water the plants",
    "Call the dentist",
  ]);
  assert.equal(remaining(document), "2 left");
  assert.deepEqual(calls.map((call) => call.method), ["GET"]);
});

test("filter case 2: Active shows only open todos and keeps the full open count", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
      { id: 3, title: "Call the dentist", done: false },
    ],
  });
  const { document, calls } = await env.start();

  filterButton(document, "Active").click();
  await flush();

  assert.equal(selectedFilter(document), "Active");
  assert.equal(filterButton(document, "Active").getAttribute("aria-pressed"), "true");
  assert.equal(filterButton(document, "All").getAttribute("aria-pressed"), "false");
  assert.deepEqual(titles(document), ["Water the plants", "Call the dentist"]);
  assert.equal(remaining(document), "2 left");
  assert.equal(calls.filter((call) => call.method === "GET").length, 1);
});

test("filter case 3: Done shows only completed todos and keeps the full open count", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
      { id: 3, title: "Call the dentist", done: false },
    ],
  });
  const { document, calls } = await env.start();

  filterButton(document, "Done").click();
  await flush();

  assert.equal(selectedFilter(document), "Done");
  assert.equal(filterButton(document, "Done").getAttribute("aria-pressed"), "true");
  assert.deepEqual(titles(document), ["Buy milk"]);
  assert.equal(remaining(document), "2 left");
  assert.equal(calls.filter((call) => call.method === "GET").length, 1);
});

test("filter case 4: All after Active or Done restores every todo in insertion order", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
      { id: 3, title: "Call the dentist", done: false },
    ],
  });
  const { document } = await env.start();

  filterButton(document, "Active").click();
  await flush();
  filterButton(document, "All").click();
  await flush();
  assert.deepEqual(titles(document), [
    "Buy milk",
    "Water the plants",
    "Call the dentist",
  ]);

  filterButton(document, "Done").click();
  await flush();
  filterButton(document, "All").click();
  await flush();
  assert.deepEqual(titles(document), [
    "Buy milk",
    "Water the plants",
    "Call the dentist",
  ]);
});

test("filter case 5: clicking the selected tab changes nothing and sends no request", async () => {
  const env = setup();
  const { document, calls } = await env.start();

  filterButton(document, "Active").click();
  await flush();
  const before = titles(document);
  const beforeCount = remaining(document);
  const beforeCalls = calls.length;

  filterButton(document, "Active").click();
  await flush();

  assert.equal(selectedFilter(document), "Active");
  assert.deepEqual(titles(document), before);
  assert.equal(remaining(document), beforeCount);
  assert.equal(calls.length, beforeCalls);
});

test("filter case 6: an empty filter renders no rows and keeps the full open count", async () => {
  const open = setup({ todos: [{ id: 1, title: "Still open", done: false }] });
  const openStarted = await open.start();
  filterButton(openStarted.document, "Done").click();
  await flush();
  assert.deepEqual(titles(openStarted.document), []);
  assert.equal(remaining(openStarted.document), "1 left");

  const done = setup({ todos: [{ id: 1, title: "Already done", done: true }] });
  const doneStarted = await done.start();
  filterButton(doneStarted.document, "Active").click();
  await flush();
  assert.deepEqual(titles(doneStarted.document), []);
  assert.equal(remaining(doneStarted.document), "Nothing left");

  const empty = setup({ todos: [] });
  const emptyStarted = await empty.start();
  assert.deepEqual(titles(emptyStarted.document), []);
  assert.equal(remaining(emptyStarted.document), "Nothing left");
});

test("filter case 7: adding under Active shows the new todo, while adding under Done keeps it hidden", async () => {
  const active = setup({ todos: [{ id: 1, title: "Existing open", done: false }] });
  const activeStarted = await active.start();
  filterButton(activeStarted.document, "Active").click();
  await flush();

  const activeInput = activeStarted.document.querySelector('form.add input[name="title"]');
  activeInput.value = "New active";
  submit(activeStarted.document.querySelector("form.add"));
  await flush();

  assert.equal(selectedFilter(activeStarted.document), "Active");
  assert.deepEqual(titles(activeStarted.document), ["Existing open", "New active"]);
  assert.equal(remaining(activeStarted.document), "2 left");

  const done = setup({ todos: [{ id: 1, title: "Finished", done: true }] });
  const doneStarted = await done.start();
  filterButton(doneStarted.document, "Done").click();
  await flush();

  const doneInput = doneStarted.document.querySelector('form.add input[name="title"]');
  doneInput.value = "Hidden while done";
  submit(doneStarted.document.querySelector("form.add"));
  await flush();

  const post = doneStarted.calls.find((call) => call.method === "POST");
  assert.ok(post, "adding should POST to the API");
  assert.deepEqual(post.body, { title: "Hidden while done" });
  assert.equal(selectedFilter(doneStarted.document), "Done");
  assert.deepEqual(titles(doneStarted.document), ["Finished"]);
  assert.equal(remaining(doneStarted.document), "1 left");

  filterButton(doneStarted.document, "Active").click();
  await flush();
  assert.deepEqual(titles(doneStarted.document), ["Hidden while done"]);

  filterButton(doneStarted.document, "All").click();
  await flush();
  assert.deepEqual(titles(doneStarted.document), ["Finished", "Hidden while done"]);
});

test("filter case 8: toggling out of the active filter patches, updates the count, and keeps the todo", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Open job", done: false },
      { id: 2, title: "Done job", done: true },
    ],
  });
  const { document, calls, state } = await env.start();

  filterButton(document, "Active").click();
  await flush();
  assert.deepEqual(titles(document), ["Open job"]);

  rowFor(document, "Open job").querySelector(".toggle").click();
  await flush();

  const activePatch = calls.filter((call) => call.method === "PATCH").at(-1);
  assert.equal(activePatch.url, "/api/todos/1");
  assert.deepEqual(activePatch.body, { done: true });
  assert.equal(selectedFilter(document), "Active");
  assert.deepEqual(titles(document), []);
  assert.equal(remaining(document), "Nothing left");
  assert.equal(state.find((todo) => todo.id === 1).done, true);

  filterButton(document, "Done").click();
  await flush();
  assert.deepEqual(titles(document), ["Open job", "Done job"]);

  rowFor(document, "Done job").querySelector(".toggle").click();
  await flush();

  const donePatch = calls.filter((call) => call.method === "PATCH").at(-1);
  assert.equal(donePatch.url, "/api/todos/2");
  assert.deepEqual(donePatch.body, { done: false });
  assert.equal(selectedFilter(document), "Done");
  assert.deepEqual(titles(document), ["Open job"]);
  assert.equal(remaining(document), "1 left");
  assert.equal(state.find((todo) => todo.id === 2).done, false);
});

test("filter case 9: editing and deleting stay in the active filter, and switching tabs cancels an open edit", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Open one", done: false },
      { id: 2, title: "Done one", done: true },
      { id: 3, title: "Open two", done: false },
      { id: 4, title: "Done two", done: true },
    ],
  });
  const { document, calls } = await env.start();

  filterButton(document, "Active").click();
  await flush();
  let form = openEditor(document, 1);
  form.querySelector('input[name="title"]').value = "Open one edited";
  submit(form);
  await flush();
  assert.equal(selectedFilter(document), "Active");
  assert.deepEqual(titles(document), ["Open one edited", "Open two"]);

  rowById(document, 3).querySelector(".delete").click();
  await flush();
  assert.equal(selectedFilter(document), "Active");
  assert.deepEqual(titles(document), ["Open one edited"]);

  filterButton(document, "Done").click();
  await flush();
  form = openEditor(document, 2);
  form.querySelector('input[name="title"]').value = "Done one edited";
  submit(form);
  await flush();
  assert.equal(selectedFilter(document), "Done");
  assert.deepEqual(titles(document), ["Done one edited", "Done two"]);

  rowById(document, 4).querySelector(".delete").click();
  await flush();
  assert.equal(selectedFilter(document), "Done");
  assert.deepEqual(titles(document), ["Done one edited"]);

  filterButton(document, "All").click();
  await flush();
  form = openEditor(document, 1);
  const beforeCancel = calls.filter((call) => call.method === "PATCH").length;
  filterButton(document, "Done").click();
  await flush();

  assert.equal(document.querySelector("form.edit"), null, "switching tabs should cancel the edit");
  assert.equal(selectedFilter(document), "Done");
  assert.deepEqual(titles(document), ["Done one edited"]);
  assert.equal(calls.filter((call) => call.method === "PATCH").length, beforeCancel);

  filterButton(document, "All").click();
  await flush();
  assert.equal(rowById(document, 1).querySelector("form.edit"), null);
  assert.equal(rowById(document, 1).querySelector(".title").textContent, "Open one edited");
});

function clearDoneButton(document) {
  return [...document.querySelectorAll(".bar button")].find(
    (button) => button.textContent === "Clear done",
  );
}

test("clear case 5: Clear done sends one request, drops done rows, and keeps active rows, count and tab", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
      { id: 3, title: "Call the dentist", done: false },
      { id: 4, title: "Read a chapter", done: true },
    ],
  });
  const { document, calls, state } = await env.start();
  assert.equal(remaining(document), "2 left");
  assert.equal(clearDoneButton(document).disabled, false);
  const before = calls.length;

  clearDoneButton(document).click();
  await flush();

  const newCalls = calls.slice(before);
  assert.equal(newCalls.length, 1, "clearing should send exactly one request");
  assert.equal(newCalls[0].method, "DELETE");
  assert.equal(newCalls[0].url, "/api/todos/done");
  assert.deepEqual(titles(document), ["Water the plants", "Call the dentist"]);
  assert.equal(remaining(document), "2 left");
  assert.equal(selectedFilter(document), "All");
  assert.deepEqual(
    state.map((todo) => todo.id),
    [2, 3],
  );
});

test("clear case 6: clearing under Done or Active keeps the other items and the selected tab", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
      { id: 3, title: "Call the dentist", done: false },
      { id: 4, title: "Read a chapter", done: true },
    ],
  });
  const { document, calls } = await env.start();

  filterButton(document, "Done").click();
  await flush();
  assert.deepEqual(titles(document), ["Buy milk", "Read a chapter"]);

  clearDoneButton(document).click();
  await flush();

  assert.equal(selectedFilter(document), "Done");
  assert.deepEqual(titles(document), []);
  assert.equal(calls.filter((call) => call.method === "DELETE").length, 1);
  assert.equal(remaining(document), "2 left");

  filterButton(document, "All").click();
  await flush();
  assert.deepEqual(titles(document), ["Water the plants", "Call the dentist"]);
  filterButton(document, "Active").click();
  await flush();
  assert.deepEqual(titles(document), ["Water the plants", "Call the dentist"]);

  const active = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
      { id: 3, title: "Call the dentist", done: false },
      { id: 4, title: "Read a chapter", done: true },
    ],
  });
  const activeStarted = await active.start();
  filterButton(activeStarted.document, "Active").click();
  await flush();
  assert.deepEqual(titles(activeStarted.document), ["Water the plants", "Call the dentist"]);

  clearDoneButton(activeStarted.document).click();
  await flush();

  assert.equal(selectedFilter(activeStarted.document), "Active");
  assert.deepEqual(titles(activeStarted.document), ["Water the plants", "Call the dentist"]);
  const deletes = activeStarted.calls.filter((call) => call.method === "DELETE");
  assert.equal(deletes.length, 1);
  assert.equal(deletes[0].url, "/api/todos/done");
  assert.equal(remaining(activeStarted.document), "2 left");
});

test("clear case 7: with nothing done the button is disabled and sends no request", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Water the plants", done: false },
      { id: 2, title: "Call the dentist", done: false },
    ],
  });
  const { document, calls } = await env.start();
  const button = clearDoneButton(document);
  assert.equal(button.disabled, true);
  const before = calls.length;

  button.click();
  await flush();

  assert.equal(calls.length, before);
  assert.deepEqual(titles(document), ["Water the plants", "Call the dentist"]);
  assert.equal(remaining(document), "2 left");
});

test("clear case 8: a failed clear shows the detail and keeps every completed item", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
    ],
    handler: async ({ url, method }) => {
      if (method === "DELETE" && url === "/api/todos/done") {
        return response(500, { detail: "Could not clear the done to-dos." });
      }
      return null;
    },
  });
  const { document, calls } = await env.start();
  const before = titles(document);

  clearDoneButton(document).click();
  await flush();

  assert.equal(calls.filter((call) => call.method === "DELETE").length, 1);
  const error = document.querySelector(".error");
  assert.equal(error.hidden, false);
  assert.equal(error.textContent, "Could not clear the done to-dos.");
  assert.deepEqual(titles(document), before);
  assert.equal(remaining(document), "1 left");

  const offline = setup({
    todos: [
      { id: 1, title: "Buy milk", done: true },
      { id: 2, title: "Water the plants", done: false },
    ],
    handler: async ({ url, method }) => {
      if (method === "DELETE" && url === "/api/todos/done") {
        throw new Error("Network down");
      }
      return null;
    },
  });
  const offlineStarted = await offline.start();
  const offlineBefore = titles(offlineStarted.document);

  clearDoneButton(offlineStarted.document).click();
  await flush();

  const offlineError = offlineStarted.document.querySelector(".error");
  assert.equal(offlineError.hidden, false);
  assert.equal(offlineError.textContent, "Network down");
  assert.deepEqual(titles(offlineStarted.document), offlineBefore);
});

test("clear case 9: clearing closes an editor on a done item and keeps one on an active item", async () => {
  const env = setup({
    todos: [
      { id: 1, title: "Done one", done: true },
      { id: 2, title: "Open one", done: false },
    ],
  });
  const { document } = await env.start();

  openEditor(document, 1);
  clearDoneButton(document).click();
  await flush();

  assert.equal(rowById(document, 1), null);
  assert.equal(document.querySelector("form.edit"), null);
  assert.deepEqual(titles(document), ["Open one"]);

  const active = setup({
    todos: [
      { id: 1, title: "Done one", done: true },
      { id: 2, title: "Open one", done: false },
    ],
  });
  const activeStarted = await active.start();
  const form = openEditor(activeStarted.document, 2);
  form.querySelector('input[name="title"]').value = "Half typed";

  clearDoneButton(activeStarted.document).click();
  await flush();

  const editor = rowById(activeStarted.document, 2).querySelector("form.edit");
  assert.ok(editor, "an active item's editor should stay open");
  assert.equal(editor.querySelector('input[name="title"]').value, "Open one");
  assert.equal(rowById(activeStarted.document, 1), null);
});
