export function createApp({
  document: doc = globalThis.document,
  fetch: fetchImpl = globalThis.fetch?.bind(globalThis),
} = {}) {
  if (!doc) throw new Error("A document is required to start the to-do app.");
  if (!fetchImpl) throw new Error("fetch is required to start the to-do app.");

  const root = doc.getElementById("app");
  if (!root) throw new Error("The to-do app needs an #app element.");

  let todos = [];
  let editingId = null;
  let filter = "all";

  root.innerHTML = `
    <div class="head">
      <h1>To-dos</h1>
      <p class="remaining" role="status"></p>
    </div>
    <div class="bar">
      <div class="filters">
        <button type="button" class="filter active" data-filter="all" aria-pressed="true">All</button>
        <button type="button" class="filter" data-filter="active" aria-pressed="false">Active</button>
        <button type="button" class="filter" data-filter="done" aria-pressed="false">Done</button>
      </div>
    </div>
    <p class="error" role="alert" hidden></p>
    <ul class="todos"></ul>
    <form class="add">
      <input name="title" placeholder="What needs doing?" aria-label="New to-do" autocomplete="off">
      <button type="submit">Add</button>
    </form>
  `;

  const remaining = root.querySelector(".remaining");
  const error = root.querySelector(".error");
  const list = root.querySelector(".todos");
  const filterButtons = [...root.querySelectorAll(".filter")];
  const addForm = root.querySelector("form.add");
  const addInput = addForm.querySelector('input[name="title"]');

  function showError(message) {
    error.textContent = message;
    error.hidden = false;
  }

  function clearError() {
    error.textContent = "";
    error.hidden = true;
  }

  function errorMessage(fallback, failure) {
    if (failure && typeof failure.message === "string" && failure.message) {
      return failure.message;
    }
    return fallback;
  }

  async function failureFrom(response, fallback) {
    try {
      const body = await response.json();
      if (body && typeof body.detail === "string") return body.detail;
    } catch {
      // A failed request may not carry a JSON body.
    }
    return fallback;
  }

  async function request(url, options, fallback) {
    const response = await fetchImpl(url, options);
    if (!response.ok) {
      throw new Error(await failureFrom(response, fallback));
    }
    return response;
  }

  function jsonOptions(method, body) {
    return {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
  }

  function setFilter(next) {
    if (filter === next) return;
    filter = next;
    editingId = null;
    render();
  }

  function visibleTodos() {
    if (filter === "active") return todos.filter((todo) => !todo.done);
    if (filter === "done") return todos.filter((todo) => todo.done);
    return todos;
  }

  function render() {
    const left = todos.filter((todo) => !todo.done).length;
    remaining.textContent = left === 0 ? "Nothing left" : `${left} left`;
    for (const button of filterButtons) {
      const selected = button.dataset.filter === filter;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", String(selected));
    }
    list.replaceChildren(...visibleTodos().map(renderRow));
  }

  function renderRow(todo) {
    const row = doc.createElement("li");
    row.className = todo.done ? "todo done" : "todo";
    row.dataset.id = String(todo.id);

    if (editingId === todo.id) {
      row.classList.add("editing");
      row.append(renderEditor(todo));
      return row;
    }

    const toggle = doc.createElement("button");
    toggle.type = "button";
    toggle.className = "toggle";
    toggle.setAttribute("role", "checkbox");
    toggle.setAttribute("aria-checked", String(todo.done));
    toggle.setAttribute("aria-label", todo.title);
    toggle.addEventListener("click", () => {
      void toggleTodo(todo);
    });

    const title = doc.createElement("span");
    title.className = "title";
    if (todo.done) {
      const struck = doc.createElement("s");
      struck.textContent = todo.title;
      title.append(struck);
    } else {
      title.textContent = todo.title;
    }

    const edit = doc.createElement("button");
    edit.type = "button";
    edit.className = "edit";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => {
      editingId = todo.id;
      clearError();
      render();
      const input = list.querySelector(`li[data-id="${todo.id}"] form.edit input`);
      input?.focus();
    });

    const remove = doc.createElement("button");
    remove.type = "button";
    remove.className = "delete";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => {
      void deleteTodo(todo);
    });

    row.append(toggle, title, edit, remove);

    row.addEventListener("click", (event) => {
      if (event.target.closest?.(".toggle, .edit, .delete")) return;

      const selection = doc.getSelection?.();
      if (
        selection &&
        !selection.isCollapsed &&
        selection.toString().length > 0 &&
        selection.anchorNode &&
        row.contains(selection.anchorNode)
      ) {
        return;
      }

      void toggleTodo(todo);
    });

    return row;
  }

  function cancelEdit() {
    editingId = null;
    clearError();
    render();
  }

  function renderEditor(todo) {
    const form = doc.createElement("form");
    form.className = "edit";

    const input = doc.createElement("input");
    input.type = "text";
    input.name = "title";
    input.value = todo.title;
    input.setAttribute("aria-label", "Edit title");
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !event.isComposing) {
        cancelEdit();
      }
    });

    const save = doc.createElement("button");
    save.type = "submit";
    save.textContent = "Save";

    const cancel = doc.createElement("button");
    cancel.type = "button";
    cancel.className = "cancel";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", cancelEdit);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void saveEdit(todo, input.value);
    });

    form.append(input, save, cancel);
    return form;
  }

  function replaceTodo(updated) {
    const index = todos.findIndex((todo) => todo.id === updated.id);
    if (index !== -1) todos[index] = updated;
  }

  async function load() {
    try {
      const response = await request("/api/todos", undefined, "Could not load to-dos.");
      const body = await response.json();
      todos = Array.isArray(body.todos) ? body.todos : [];
      render();
    } catch (failure) {
      render();
      showError(errorMessage("Could not load to-dos.", failure));
    }
  }

  async function addTodo(value) {
    const title = value.trim();
    if (!title) return;

    try {
      clearError();
      const response = await request(
        "/api/todos",
        jsonOptions("POST", { title }),
        "Could not add the to-do.",
      );
      todos.push(await response.json());
      addInput.value = "";
      render();
    } catch (failure) {
      showError(errorMessage("Could not add the to-do.", failure));
    }
  }

  async function toggleTodo(todo) {
    try {
      clearError();
      const response = await request(
        `/api/todos/${todo.id}`,
        jsonOptions("PATCH", { done: !todo.done }),
        "Could not change the to-do.",
      );
      replaceTodo(await response.json());
      render();
    } catch (failure) {
      showError(errorMessage("Could not change the to-do.", failure));
    }
  }

  async function saveEdit(todo, value) {
    const title = value.trim();
    if (!title) return;

    try {
      clearError();
      const response = await request(
        `/api/todos/${todo.id}`,
        jsonOptions("PATCH", { title }),
        "Could not save the title.",
      );
      replaceTodo(await response.json());
      editingId = null;
      render();
    } catch (failure) {
      showError(errorMessage("Could not save the title.", failure));
    }
  }

  async function deleteTodo(todo) {
    try {
      clearError();
      await request(
        `/api/todos/${todo.id}`,
        { method: "DELETE" },
        "Could not delete the to-do.",
      );
      todos = todos.filter((one) => one.id !== todo.id);
      if (editingId === todo.id) editingId = null;
      render();
    } catch (failure) {
      showError(errorMessage("Could not delete the to-do.", failure));
    }
  }

  addForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void addTodo(addInput.value);
  });

  for (const button of filterButtons) {
    button.addEventListener("click", () => setFilter(button.dataset.filter));
  }

  return {
    async start() {
      await load();
    },
  };
}
