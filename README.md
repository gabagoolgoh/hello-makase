# makase-todo

A one-page to-do app, served by FastAPI, to try makase on. The page lists your to-dos and has
a form to add one. The to-dos live in memory: a few are loaded when the app starts, and
nothing survives a restart.

Two specs come with it. *Mark a to-do done* is already built: makase runs its tests and
brings it to *Test* and *Merge* a few minutes after you import, where you open this page with
the change in it. *Show how many are left* waits for you to approve it, so you can watch makase
build one.

Run it locally:

    uv run uvicorn app.main:app

Then open http://127.0.0.1:8000/.

Test it:

    uv sync --all-extras
    uv run pytest
