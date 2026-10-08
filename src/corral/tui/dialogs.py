"""Modal dialogs shared by the main screen and the settings screen."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, SelectionList, Static
from textual.widgets.option_list import Option

from corral import labels, ops
from corral.config import Config, ModelSpec
from corral.projects import AgentTab


class AgentPicker(ModalScreen[str | None]):
    """Pick a model, then an effort. Returns a "key/effort" spec."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, cfg: Config, project: str = "", title: str = "") -> None:
        super().__init__()
        self.cfg = cfg
        self.title_text = title or f"New agent tab for [b]{project}[/b]"
        self.model: ModelSpec | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title")
            with Horizontal(id="picker"):
                yield OptionList(
                    *[
                        Option(f"{m.display}  [dim]{m.tool}[/dim]", id=m.key)
                        for m in self.cfg.models
                    ],
                    id="models",
                )
                yield OptionList(id="efforts")
            yield Label("[dim]enter: choose  ←/→: switch list  esc: cancel[/dim]")

    def on_mount(self) -> None:
        models = self.query_one("#models", OptionList)
        keys = [m.key for m in self.cfg.models]
        default = ops.parse_spec(self.cfg.default_agents[0])[0] if self.cfg.default_agents else ""
        models.highlighted = keys.index(default) if default in keys else 0
        models.focus()

    @on(OptionList.OptionHighlighted, "#models")
    def model_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id is None:
            return
        self.model = self.cfg.model(event.option.id)
        efforts = self.query_one("#efforts", OptionList)
        levels = self.cfg.efforts_of(self.model)
        efforts.clear_options()
        efforts.add_options([Option(labels.tab_label(self.model.display, e), id=e) for e in levels])
        efforts.highlighted = levels.index("medium") if "medium" in levels else 0

    @on(OptionList.OptionSelected, "#models")
    def model_selected(self) -> None:
        self.query_one("#efforts", OptionList).focus()

    @on(OptionList.OptionSelected, "#efforts")
    def effort_selected(self, event: OptionList.OptionSelected) -> None:
        if self.model:
            self.dismiss(f"{self.model.key}/{event.option.id}")

    def key_right(self) -> None:
        self.query_one("#efforts", OptionList).focus()

    def key_left(self) -> None:
        self.query_one("#models", OptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)


class StopPicker(ModalScreen[list[str] | None]):
    """Choose running agents to stop. Returns pane ids."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("s", "stop", "Stop selected"),
        Binding("a", "select_all", "Select all"),
    ]

    def __init__(self, title: str, agents: list[AgentTab]) -> None:
        super().__init__()
        self.title_text = title
        self.agents = agents

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title")
            yield SelectionList[str](
                *[
                    (f"{a.label}  [dim]{a.status} · {a.name or a.pane_id}[/dim]", a.pane_id)
                    for a in self.agents
                ],
                id="agents",
            )
            yield Label(
                "[dim]space: toggle  a: all  s: stop selected  esc: cancel\n"
                "Stopping closes the agent's pane.[/dim]"
            )

    def action_select_all(self) -> None:
        self.query_one(SelectionList).select_all()

    def action_stop(self) -> None:
        chosen = list(self.query_one(SelectionList).selected)
        self.dismiss(chosen or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Confirm(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "answer(True)", "Yes"),
        Binding("n,escape", "answer(False)", "No"),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title")
            with VerticalScroll(id="confirm-body"):
                yield Static(Text(self.body))
            yield Label("[b]y[/b] proceed   [b]n[/b] cancel")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)
