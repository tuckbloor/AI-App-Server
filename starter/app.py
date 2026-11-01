"""Clean example application: local Ollama prompt + Python UI layout guide.

This is a developer sample, not a mandatory server management screen. You may
replace this file completely when building your own project.
"""
from urllib.error import HTTPError, URLError

import ai_app_server as ui
from ai_app_server.ollama import generate

ui.title('Your AI workspace')
ui.caption('LOCAL AI  /  PYTHON APP STARTER')
ui.text('Choose a model, write your instructions and press Generate response. You can replace any of these components with your own project interface.')

with ui.sidebar():
    ui.section('Ollama models')
    model = ui.ollama_model_select('Installed model', key='model')
    ui.caption('Models are read from Ollama running on your own computer.')
    ui.guide('No models listed? Start Ollama, then install a model using: ollama pull llama3.2')

ui.section('Ask your local AI')
prompt = ui.text_area(
    'Your instructions / prompt',
    'Explain how I can use Python to build a useful AI tool.',
    key='prompt',
    height=170,
)

state = ui.session_state()
if ui.button('Generate response', key='generate'):
    state.pop('answer', None)
    state.pop('answer_model', None)
    if not model:
        ui.warning('No Ollama model is available. Start Ollama and install a model, then refresh this page.')
    elif not prompt.strip():
        ui.warning('Enter your instructions before generating a response.')
    else:
        try:
            answer = generate(prompt, model)
            if not answer.strip():
                ui.warning('Ollama returned an empty response. Try again or choose another model.')
            else:
                state['answer'] = answer
                state['answer_model'] = model
        except HTTPError as exc:
            ui.error(f'Ollama returned HTTP {exc.code}. Check that the selected model is available and try again.')
        except (URLError, ConnectionError) as exc:
            ui.error('Cannot connect to Ollama. Start Ollama on your computer and try again.')
        except TimeoutError:
            ui.error('Ollama took too long to respond. Try a smaller model or shorter instructions.')
        except ValueError as exc:
            ui.error(f'Cannot generate response: {exc}')
        except Exception as exc:
            ui.error(f'Ollama error ({type(exc).__name__}). Check the server console for details.')

if state.get('answer'):
    ui.divider()
    ui.section('Model response')
    ui.caption(f"GENERATED LOCALLY WITH {state['answer_model']}")
    ui.output(state['answer'])

ui.divider()
ui.section('Build your own Python application')
ui.text('Everything you see on this page is defined in examples/app.py. Replace the example or use these components in your own app.py.')
ui.guide('LEFT SIDEBAR: Place model selectors, filters or settings inside with ui.sidebar():')
ui.guide('MAIN SCREEN: Put text inputs, buttons, tables, results and charts directly in your Python script, outside the sidebar block.')
ui.code('''import ai_app_server as ui

ui.title("My AI Project")
with ui.sidebar():
    model = ui.ollama_model_select("Model")

prompt = ui.text_area("Instructions")
if ui.button("Run"):
    ui.success("Put your Python logic here")''')
ui.caption('Run your own script: ai-app-server run app.py')
