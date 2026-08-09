# developing-with-streamlit

This was previously a symlink into `.venv/lib/python3.12/site-packages/...` — a
POSIX path from the machine this repo was first developed on. It could not
resolve on Windows (venvs use `.venv\Lib\site-packages\`) and resolves nowhere
at all now that the project runs in Docker with no host venv. It is a pointer
file instead so the repo stops carrying a broken link.

## Where the real skill lives

The skill ships inside the installed `streamlit` package. Resolve it in-container:

```powershell
docker compose run --rm sim python -c "import streamlit,pathlib;print(pathlib.Path(streamlit.__file__).parent/'.agents'/'skills'/'developing-with-streamlit')"
```

Read `SKILL.md` there, then follow its routing table into `references/`.

If no container is available, the skill is inside the streamlit wheel on PyPI
(wheels are plain zip archives): download it and extract
`streamlit/.agents/skills/developing-with-streamlit/`.

## Rules this skill imposes on our dashboard code

These are the ones our code has to obey — read the real skill for the rest.

- **Multipage:** `st.navigation` + `st.Page` with an `app_pages/` folder. Not a
  legacy `pages/` directory.
- **No CSS injection for layout.** Prefer native elements: `st.container(border=True)`,
  `st.container(horizontal=True)`, and `.streamlit/config.toml` for theming.
- **`width="stretch"`**, never the deprecated `use_container_width`.
- **`st.iframe` / `st.html`**, never the deprecated `st.components.v1.*`.
- **`st.cache_resource`** for the MQTT client and the ML model — exactly one of
  each per app, surviving reruns and page navigation.
- **`st.fragment(run_every=...)`** for auto-refreshing sections.
- Prefer Vega charts (`st.line_chart`, `st.altair_chart`) over Plotly.
- Prefer `st.segmented_control` over `st.radio(..., horizontal=True)`.
- Prefer Material Symbols (`:material/hvac:`) over emoji; sentence case for labels.

`dashboard/app.py` (Project 1) predates this skill and violates several of these.
Task 9 of the Project-2 plan rebuilds it; do not propagate its patterns.
