#!/usr/bin/env python3
# distrobuilder-ui-experiment.py — welcome page mockup / design experiment

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Footer, Static


BUILD_TYPES = [
    {
        "id": "ISO",
        "key": "1",
        "glyph": "[ ISO ]",
        "title": "ISO Image",
        "tag": "Recommended for beginners",
        "desc": (
            "A bootable disc image that works\n"
            "on both BIOS and UEFI systems.\n"
            "The simplest way to get started."
        ),
    },
    {
        "id": "HARDDISK",
        "key": "2",
        "glyph": "[  VM  ]",
        "title": "Virtual Machine",
        "tag": "Raw .img · UEFI only",
        "desc": (
            "A cloud-style hard disk image.\n"
            "Ready to attach to QEMU,\n"
            "VMware, or VirtualBox."
        ),
    },
    {
        "id": "V86",
        "key": "3",
        "glyph": "[ v86  ]",
        "title": "v86 Browser VM",
        "tag": "32-bit · runs in a browser",
        "desc": (
            "A 9p filesystem + save state\n"
            "for the v86 x86 emulator.\n"
            "Run Linux right in the browser."
        ),
    },
]


class BuildCard(Widget):
    """A selectable card representing one build output type."""

    selected: reactive[bool] = reactive(False, recompose=False)

    DEFAULT_CSS = ""

    def __init__(self, card_id: str, key: str, glyph: str, title: str, tag: str, desc: str) -> None:
        super().__init__(id=f"card-{card_id}", classes="card")
        self.card_id = card_id
        self._key = key
        self._glyph = glyph
        self._title = title
        self._tag = tag
        self._desc = desc

    def compose(self) -> ComposeResult:
        yield Static(self._glyph, classes="card-glyph")
        yield Static(self._title, classes="card-title")
        yield Static(self._tag, classes="card-tag")
        yield Static("─" * 22, classes="card-rule")
        yield Static(self._desc, classes="card-desc")
        yield Static(f"press  {self._key}  to select", classes="card-hint")

    def on_click(self) -> None:
        for card in self.app.query(BuildCard):
            card.selected = False
        self.selected = True

    def watch_selected(self, value: bool) -> None:
        self.set_class(value, "selected")


class WelcomePage(Widget):
    """The welcome / build-type selection page."""

    def compose(self) -> ComposeResult:
        yield Static(
            "What kind of distro would you like to build?",
            id="question",
        )
        with Horizontal(id="cards"):
            for bt in BUILD_TYPES:
                yield BuildCard(
                    card_id=bt["id"],
                    key=bt["key"],
                    glyph=bt["glyph"],
                    title=bt["title"],
                    tag=bt["tag"],
                    desc=bt["desc"],
                )
        with Horizontal(id="btn-bar"):
            yield Button("Quit", variant="error", id="quit")
            yield Button("Next →", variant="primary", id="next")

    def on_mount(self) -> None:
        self.border_title = "mkmelinux - make Linux distros easily!"
        self.query_one("#card-ISO", BuildCard).selected = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()
        elif event.button.id == "next":
            selected = next(
                (c for c in self.query(BuildCard) if c.selected), None
            )
            if selected:
                self.notify(f"Selected: {selected.card_id}  (next page would go here)")


class ExperimentApp(App):
    TITLE = "mkmelinux distrobuilder"

    CSS = """
    Screen {
        background: $background;
    }

    WelcomePage {
        width: 1fr;
        height: 1fr;
        margin: 1 2;
        layout: vertical;
        align: center middle;
        border: round $primary;
        border-title-align: left;
        border-title-color: $primary;
        border-title-style: bold;
        padding: 1 2;
    }

    #question {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }

    /* ── card grid ─────────────────────────────────────────── */

    #cards {
        width: 90%;
        height: auto;
        align: center middle;
    }

    .card {
        width: 1fr;
        height: auto;
        layout: vertical;
        border: round $panel;
        background: $surface;
        padding: 1 2;
        margin: 0 1;
        align: center middle;
    }

    .card:hover {
        border: round $primary-lighten-1;
        background: $surface-lighten-1;
    }

    .card.selected {
        border: round $success;
        background: $surface-lighten-1;
    }

    /* ── card internals ─────────────────────────────────────── */

    .card-glyph {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $primary;
        padding: 1 0;
    }

    .card.selected .card-glyph {
        color: $success;
    }

    .card-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 0;
    }

    .card-tag {
        width: 100%;
        text-align: center;
        color: $text-muted;
        text-style: italic;
    }

    .card.selected .card-tag {
        color: $success-darken-1;
    }

    .card-rule {
        width: 100%;
        text-align: center;
        color: $panel-lighten-1;
        margin: 1 0;
    }

    .card.selected .card-rule {
        color: $success-darken-2;
    }

    .card-desc {
        width: 100%;
        color: $text-muted;
        margin-bottom: 1;
    }

    .card-hint {
        width: 100%;
        text-align: center;
        color: $panel-lighten-2;
    }

    .card.selected .card-hint {
        color: $success;
        text-style: bold;
    }

    /* ── bottom bar ─────────────────────────────────────────── */

    #btn-bar {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0;
    }

    #btn-bar Button {
        margin: 0 2;
        min-width: 12;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("1", "select('ISO')", "ISO"),
        ("2", "select('HARDDISK')", "VM"),
        ("3", "select('V86')", "v86"),
        ("enter", "next", "Next"),
    ]

    def compose(self) -> ComposeResult:
        yield WelcomePage()
        yield Footer()

    def action_select(self, card_id: str) -> None:
        for card in self.query(BuildCard):
            card.selected = False
        self.query_one(f"#card-{card_id}", BuildCard).selected = True

    def action_next(self) -> None:
        selected = next((c for c in self.query(BuildCard) if c.selected), None)
        if selected:
            self.notify(f"Selected: {selected.card_id}  (next page would go here)")


if __name__ == "__main__":
    ExperimentApp().run()
