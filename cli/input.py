import shutil

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory


class InputPrompt:
    def __init__(self):
        self._create_session()

    def _create_session(self):
        """Create or recreate the prompt session."""
        self.session = PromptSession(
            history=InMemoryHistory(),
            auto_suggest=AutoSuggestFromHistory(),
            style=Style.from_dict({
                'prompt':         'ansiblue bold',
                'separator':      '#555555',
                'bottom-toolbar': 'noreverse bg:default #555555',
            })
        )

    def reset(self):
        """Reset the session after terminal state changes (e.g., after pty.spawn)."""
        self._create_session()

    def get_input(self, prompt_text: str = "you: ", bottom_toolbar=None) -> str:
        cols = shutil.get_terminal_size((80, 24)).columns
        message = FormattedText([
            ('class:separator', '─' * cols + '\n'),
            ('class:prompt',    prompt_text),
        ])
        return self.session.prompt(message, bottom_toolbar=bottom_toolbar)
