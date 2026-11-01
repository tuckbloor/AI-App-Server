# AI App Server — developer guide (v0.6.0)

AI App Server is a **Python-to-browser application framework**. You do not need Streamlit, Node, or a separate hosted service. Every part of the public app UI comes from **your own Python source**.

## Create a new app

From PowerShell (assuming the package source is at `E:\ai-app-server`):

```powershell
mkdir E:\my-ai-project
cd E:\my-ai-project
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e E:\ai-app-server\engine
```

Create `app.py`:

```python
import ai_app_server as ui

ui.title('My AI Project')
with ui.sidebar():
    ui.section('Settings')
    mode = ui.selectbox('Task type', ['Review', 'Summarise'])

instructions = ui.text_area('Instructions', 'Tell me about...')
if ui.button('Run'):
    ui.success(f'Task: {mode}')
    ui.text(instructions)
```

Launch:

```powershell
.\.venv\Scripts\ai-app-server.exe run app.py
```

Then visit `http://127.0.0.1:8501/`. Server administrator tools live at `/admin` and are **not part of the end-user application**.

## UI layout is under your control

- **Left sidebar:** Everything placed inside `with ui.sidebar():` appears in the sidebar. Model dropdowns, checkboxes, configuration, filters, and text fields are common choices.
- **Main content:** Calls outside any sidebar or column block appear in the main page, in their source-code order.
- **Columns:** Use `left, right = ui.columns(2)`; then `with left:` and `with right:` to arrange sections horizontally.
- **Labels / guidance:** `ui.title`, `ui.heading`, `ui.section`, `ui.caption`, `ui.guide`, and `ui.code` make it easy to explain the developer's app.
- **Controls:** `ui.text_area`, `ui.input`, `ui.number_input`, `ui.checkbox`, `ui.selectbox`, and `ui.button` supply user inputs.
- **Output:** `ui.text`, `ui.success`, `ui.warning`, `ui.error`, `ui.table`, and `ui.metric` show results.

## Ollama model selector

Ollama is **optional**. If you want to use local AI models, install and run Ollama separately and download at least one model (for example: `ollama pull llama3.2`). Our framework queries Ollama's own local API; it does not upload your data to AI App Server infrastructure.

```python
import ai_app_server as ui
from ai_app_server.ollama import generate

with ui.sidebar():
    model = ui.ollama_model_select('Choose an Ollama model')

prompt = ui.text_area('Instructions')
state = ui.session_state()
if ui.button('Run AI'):
    if model and prompt.strip():
        try:
            state['answer'] = generate(prompt, model)
        except Exception as exc:
            ui.error(f'Model request failed: {type(exc).__name__}')
    else:
        ui.warning('Choose an installed Ollama model and enter a prompt.')

if state.get('answer'):
    ui.section('Model response')
    ui.output(state['answer'])
```

The default local Ollama API address is `http://127.0.0.1:11434`. A trusted alternate origin can be configured by the process owner using `AI_APP_SERVER_OLLAMA_URL` (e.g. when an Ollama instance runs on another machine). Never expose an unauthenticated Ollama endpoint publicly. `ui.session_state()` is an isolated dictionary for each connected browser, useful for retaining AI responses after widget changes; it is not permanent storage. The Generate button displays a loading state while a local model is responding.

## Sample app and source layout

The included `starter/app.py` is a developer tutorial copied to `app/app.py` on new installations (older v0.5 projects retain `examples/app.py`) — not a mandatory welcome page. It deliberately has no Project Options, project-type selector, developer-name field, or Show Developer Instructions checkbox. Replace that file or launch any `app.py`. The server automatically renders the selected script in a browser.

Your scripts are re-executed when users change widgets. Keep expensive model initialization, background tasks, long-lived data, and application state in your own services or storage. This release has **no full Streamlit compatibility**, no drag-and-drop design editor, and no built-in isolation of arbitrary Python scripts.

## Server administration and password recovery

The server admin remains `/admin`. On first login (`admin` / `password`) you must set a strong new password **and a valid recovery email**. A validly formatted email is **not yet verified**. Configure SMTP email delivery using the example file `.env.smtp.example`, restart the server, and use the verification email link to prove mailbox ownership. Without SMTP, password recovery **cannot send email**, though ordinary administrator login works.

Reset links expire after 30 minutes and can be used once. Administrators can resend verification from the **Security** section. For production, configure `AI_APP_SERVER_PUBLIC_ORIGIN` to the actual HTTPS address and use an HTTPS reverse proxy with proper host validation. Do not use this developer release for public untrusted workloads without further security hardening.

## Modular upgrades

Since v0.6.0, the installed framework lives in `engine/` and everything the developer owns remains outside it. Use `UPDATE ENGINE.bat` and select a future release ZIP. Only the engine is swapped. The updater saves a consistent SQLite snapshot and previous engine; it never overwrites existing `app/`, `examples/`, `config/` or `data/`. Development `app.py` scripts should not be stored within the framework engine.
