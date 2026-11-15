# Writing documentation

This site is built with [MkDocs](https://www.mkdocs.org/), the [Material](https://squidfunk.github.io/mkdocs-material/)
theme and [mkdocstrings](https://mkdocstrings.github.io/). The configuration is `backend/mkdocs.yml`; pages live in
`backend/docs/`.

## Two kinds of pages

| Kind | Where | Source of truth |
|---|---|---|
| **Guides** | `docs/*.md`, `docs/concepts/`, `docs/api/`, `docs/pipeline/`, `docs/operations/`, `docs/development/` | Written by hand |
| **API reference** | `docs/reference/*.md` | Generated from **docstrings** in the Python code |

A reference page is just a title and a directive:

```markdown
# analytics

Calculations on top of the calendar: coloring levels, harmonization, anomalies.

::: analytics
```

`::: analytics` makes mkdocstrings render the module's docstring and the docstrings of its public functions and
classes. The pipeline page uses one directive per module (`::: fires_data.store`, and so on).

Documentation is generated **statically** (the code is parsed, not imported), so building the site does not need
the database, the NASA key or any running service.

## Build and preview

Run from `backend/`:

```bash
pip install -r requirements-docs.txt
mkdocs serve                  # live preview, reloads on save
mkdocs build --strict         # builds into site/, and fails on broken links or unresolved references
```

`mkdocs build --strict` is the right check before sharing the site. `site/` is generated output and should not be
committed. Because `use_directory_urls: false`, the built site can also be opened straight from disk
(`site/index.html`), though search needs a web server.

## Writing good docstrings

mkdocstrings renders docstrings as **Markdown**, in the plain style this codebase already uses:

```python
def level(value, breaks):
    """0 — no fires, 1..4 — from weak to strong activity, None — no data."""
```

Guidelines:

- **First line**: one sentence saying what the function does. It becomes the summary.
- **Why, not how.** The code already shows how; explain the reason, the units and the pitfalls (for example
  "`None` means not loaded, not zero").
- **Use Markdown** for lists and code. Remember that a single line break inside a paragraph does **not** create a new
  line when rendered. Use a blank line, a bullet list or a table to separate items.
- **Private names** (starting with `_`) are hidden from the reference by default. Document only what other modules
  or users need.
- Undocumented public members still appear, empty (`show_if_no_docstring: true`). Treat an empty entry in the
  reference as a to-do item.
- FastAPI endpoint docstrings are also shown in Swagger UI at `/docs`, so write them for API consumers.

## Adding a page

1. Create the Markdown file under the right folder in `docs/`.
2. Add it to `nav:` in `mkdocs.yml`. Pages not listed in `nav` are built but have no menu entry.
3. Link to other pages with **relative file paths**, for example `[Endpoints](../api/endpoints.md)`. Use anchors
   for sections: `../api/endpoints.md#get-calendar`. Strict mode checks these.

To document a new Python module, add `docs/reference/<module>.md` with `::: <module>` and a nav entry (as done for
`geo`). The reference currently covers `main`, `frontend_api`, `store`, `reports`, `geo`, `importer`, `updater`,
`analytics`, `config` and the `fires_data` package.

## Markdown features available

Enabled in `mkdocs.yml`: admonitions, tables, tabs, code highlighting with a copy button, heading permalinks
and custom heading ids.

````markdown
!!! warning "Title"
    Indented content of the box. Types: note, info, tip, warning, danger.

=== "Windows"

    ```powershell
    .\venv\Scripts\Activate.ps1
    ```

=== "macOS / Linux"

    ```bash
    source venv/bin/activate
    ```

## A heading with a fixed anchor { #my-anchor }
````

## Where the information comes from

The guides summarize several documents that live next to the code. When the facts change, update the original and
then the guide:

| Topic | Original |
|---|---|
| Grid method | `data_pipeline/GRID_METHOD.md` |
| Harmonization experiment | `data_pipeline/CALIBRATION_METHOD.md` |
| What data is loaded right now | `data_pipeline/LIVE_STATUS.md` (a dated snapshot) |
| Pipeline commands | the "Data pipeline package" section of the repository `README.md` and `fires_data/cli.py` |
| Server setup | the repository `README.md` and the files in `backend/deploy/` |
| Endpoint behavior | `main.py` and `frontend_api.py` (the code is the source of truth) |
| Region borders | `geo.py`, `tools/build_boundaries.py` and `REGIONS` in `config.py` |

!!! tip "Keep volatile facts out of the guides"
    Counts such as "how many days are loaded" go stale quickly. Guides point to `fires_data status`, `/status` or
    `LIVE_STATUS.md` instead of repeating the numbers.
