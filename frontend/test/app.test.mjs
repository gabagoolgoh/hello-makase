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
