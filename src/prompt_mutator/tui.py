from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Collapsible,
    DataTable,
    Footer,
    Header,
    Label,
    Select,
    SelectionList,
    Static,
    TextArea,
)

from .audit import AuditBundle
from .cli import default_runs_root
from .generator import PromptGenerator
from .models import GenerationRequest, RunResult
from .profiles import load_profile


_TECHNIQUE_DESCRIPTIONS = {
    "leetspeak": "letter-to-number and symbol substitutions",
    "homoglyph": "visually similar Greek and Cyrillic characters",
    "unicode_style": "mathematical, circled, superscript, and subscript forms",
    "fullwidth": "full-width compatibility characters",
    "zero_width": "invisible separators between characters",
    "whitespace": "spacing-based character fragmentation",
    "punctuation": "punctuation-based character fragmentation",
    "random_case": "mixed upper- and lowercase letters",
    "separator": "visible separators between characters",
    "reverse": "reversed code-point order",
    "base64": "Base64-encoded UTF-8 text",
    "hex": "raw, 0xNN, and \\xNN hexadecimal forms",
    "url": "whole and selective percent encoding",
    "combining": "Unicode combining-mark noise",
    "normalization": "NFC, NFD, NFKC, and NFKD forms",
    "html_entity": "HTML numeric character references",
    "unicode_escape": "\\u, \\U, and \\N{name} escape forms",
}


class CasesSection(Vertical):
    """Generated-case pane that Textual may place in maximized view."""

    ALLOW_MAXIMIZE = True


class PromptMutatorApp(App[None]):
    """Keyboard-first interface for the primary single-prompt workflow."""

    TITLE = "LLM Red Team Workbench"
    SUB_TITLE = "Authorized internal testing"
    ALLOW_IN_MAXIMIZED_VIEW = "#controls"
    CSS = """
    Screen { layout: vertical; }
    #workspace { height: 1fr; layout: vertical; }
    #controls { height: 4; align: left top; padding: 0 1; }
    #prompt-input { height: 10; border: round $accent; }
    #cases-section { height: 3fr; min-height: 5; }
    #cases { height: 1fr; border: round $primary; }
    #detail { width: 1fr; height: 2fr; min-height: 5; border: round $secondary; padding: 0 1; }
    #case-detail-scroll { height: 1fr; overflow-y: auto; }
    #case-detail { height: auto; padding-right: 1; }
    #actions { height: 3; }
    Button { margin-right: 1; }
    Select { width: 100%; }
    .control-field { height: 4; margin-right: 1; }
    #profile-field { width: 28%; }
    #intensity-field { width: 22%; }
    #count-field { width: 16%; }
    #generate-field { width: 22%; height: 4; }
    #generate { width: 100%; margin-top: 1; }
    #toggle-cases-maximized { width: 5; min-width: 5; height: 3; margin: 1 0 0 1; }
    #custom-techniques, #custom-chain { display: none; height: auto; margin: 0 1 1 1; }
    #custom-technique-list { height: 8; margin: 0 2; }
    .panel-actions { height: 4; padding: 1 2 0 2; }
    .panel-actions Button { min-width: 18; margin-right: 2; }
    #custom-chain-steps { height: 6; padding: 0 2 1 2; }
    .chain-step { width: 1fr; height: 5; margin-right: 2; }
    .chain-step:last-child { margin-right: 0; }
    .field-label, .chain-label { height: 1; color: $text-muted; text-style: bold; }
    .pane-title { text-style: bold; }
    """
    BINDINGS = [
        ("ctrl+g", "generate", "Generate"),
        ("ctrl+r", "copy_raw", "Copy raw"),
        ("ctrl+e", "copy_escaped", "Copy escaped"),
        ("ctrl+m", "toggle_cases_maximized", "Max/restore cases"),
        Binding("f11", "toggle_cases_maximized", "Max/restore cases", show=False),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        runs_root: Path | None = None,
        config_root: Path | None = None,
        clipboard: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.runs_root = Path(runs_root) if runs_root is not None else default_runs_root()
        self.config_root = Path(config_root) if config_root is not None else self._default_config_root()
        self._clipboard_writer = clipboard or self.copy_to_clipboard
        self.result: RunResult | None = None
        self._selected_index = 0
        self._sort_column: str | None = None
        self._sort_reverse = False
        saved_theme = self._load_saved_theme()
        if saved_theme in self.available_themes:
            self.theme = saved_theme

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Prompt", classes="pane-title")
        yield TextArea(id="prompt-input", language=None, show_line_numbers=True)
        with Horizontal(id="controls"):
            with Vertical(classes="control-field", id="profile-field"):
                yield Label("Profile", classes="field-label")
                yield Select(
                    (
                        ("Baseline", "baseline"),
                        ("Unicode", "unicode"),
                        ("Encoding", "encoding"),
                        ("Comprehensive", "comprehensive"),
                        ("Chained", "chained"),
                        ("Custom techniques", "custom"),
                        ("Custom chain", "custom_chain"),
                    ),
                    value="baseline",
                    id="profile",
                    allow_blank=False,
                )
            with Vertical(classes="control-field", id="intensity-field"):
                yield Label("Intensity", classes="field-label")
                yield Select(
                    (("Low", "low"), ("Medium", "medium"), ("High", "high")),
                    value="medium",
                    id="intensity",
                    allow_blank=False,
                )
            with Vertical(classes="control-field", id="count-field"):
                yield Label("Cases", classes="field-label")
                yield Select(
                    (("25", 25), ("50", 50), ("100", 100), ("250", 250), ("500", 500), ("1,000", 1000)),
                    value=25,
                    id="case-count",
                    allow_blank=False,
                )
            with Vertical(id="generate-field"):
                yield Button("Generate cases", id="generate", variant="primary")
            toggle_cases = Button("+", id="toggle-cases-maximized")
            toggle_cases.tooltip = "Maximize Generated Cases (Ctrl+M)"
            yield toggle_cases
        with Collapsible(
            title="Custom techniques — 17 selected (Space toggles)",
            collapsed=False,
            id="custom-techniques",
        ):
            yield SelectionList(
                *(
                    (f"{name} — {_TECHNIQUE_DESCRIPTIONS[name]}", name, True)
                    for name in PromptGenerator.techniques()
                ),
                id="custom-technique-list",
            )
            with Horizontal(id="custom-technique-actions", classes="panel-actions"):
                yield Button("Select all", id="select-all-techniques", variant="primary")
                yield Button("Clear selection", id="clear-techniques")
        technique_options = tuple(
            (name.replace("_", " ").title(), name)
            for name in PromptGenerator.techniques()
        )
        with Collapsible(
            title="Custom chain — choose 2 or 3 ordered steps",
            collapsed=False,
            id="custom-chain",
        ):
            with Horizontal(id="custom-chain-steps"):
                for step in range(1, 4):
                    with Vertical(classes="chain-step"):
                        suffix = " (optional)" if step == 3 else ""
                        yield Label(f"Step {step}{suffix}", classes="chain-label")
                        yield Select(
                            technique_options,
                            prompt="Choose technique",
                            id=f"chain-step-{step}",
                            allow_blank=True,
                        )
        with Vertical(id="workspace"):
            with CasesSection(id="cases-section"):
                yield Label("Generated cases", classes="pane-title")
                yield DataTable(id="cases", cursor_type="row", zebra_stripes=True)
            with Vertical(id="detail"):
                yield Label("Case inspection", classes="pane-title")
                with Horizontal(id="actions"):
                    yield Button("Copy raw", id="copy-raw", disabled=True)
                    yield Button("Copy escaped", id="copy-escaped", disabled=True)
                    yield Button("Clear clipboard", id="clear-clipboard")
                with VerticalScroll(id="case-detail-scroll"):
                    yield Static("Generate cases to inspect them.", id="case-detail", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#cases", DataTable)
        table.add_column("Case", key="case")
        table.add_column("Technique", key="technique")
        table.add_column("Preview", key="preview")
        self.theme_changed_signal.subscribe(self, self._save_theme, immediate=True)
        self.watch(
            self.screen,
            "maximized",
            self._sync_cases_maximize_button,
            init=False,
        )
        self.query_one("#prompt-input", TextArea).focus()

    def on_resize(self, event: events.Resize) -> None:
        try:
            prompt = self.query_one("#prompt-input", TextArea)
        except NoMatches:
            return
        prompt.styles.height = 10 if event.size.height >= 32 else 6

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "generate": self.action_generate,
            "copy-raw": self.action_copy_raw,
            "copy-escaped": self.action_copy_escaped,
            "clear-clipboard": self.action_clear_clipboard,
            "select-all-techniques": self.action_select_all_techniques,
            "clear-techniques": self.action_clear_techniques,
            "toggle-cases-maximized": self.action_toggle_cases_maximized,
        }
        action = actions.get(event.button.id or "")
        if action is not None:
            action()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "profile":
            return
        techniques_panel = self.query_one("#custom-techniques", Collapsible)
        chain_panel = self.query_one("#custom-chain", Collapsible)
        techniques_panel.styles.display = "block" if event.value == "custom" else "none"
        chain_panel.styles.display = "block" if event.value == "custom_chain" else "none"

    def on_selection_list_selected_changed(
        self, event: SelectionList.SelectedChanged[str]
    ) -> None:
        if event.selection_list.id != "custom-technique-list":
            return
        count = len(event.selection_list.selected)
        self.query_one("#custom-techniques", Collapsible).title = (
            f"Custom techniques — {count} selected (Space toggles)"
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.result is None or event.cursor_row < 0:
            return
        current_key = event.data_table.coordinate_to_cell_key(
            Coordinate(event.cursor_row, 0)
        ).row_key
        self._select_case_id(str(current_key.value))

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        table = event.data_table
        column = str(event.column_key.value)
        self._sort_reverse = self._sort_column == column and not self._sort_reverse
        self._sort_column = column
        table.sort(
            event.column_key,
            key=lambda value: str(value).casefold(),
            reverse=self._sort_reverse,
        )
        labels = {"case": "Case", "technique": "Technique", "preview": "Preview"}
        for key, definition in table.columns.items():
            arrow = ""
            if key.value == column:
                arrow = " ▼" if self._sort_reverse else " ▲"
            definition.label = Text(labels[str(key.value)] + arrow)
        table.refresh(layout=True)
        if table.row_count:
            first_key = table.coordinate_to_cell_key(Coordinate(0, 0)).row_key
            table.move_cursor(row=0)
            self._select_case_id(str(first_key.value))
        direction = "descending" if self._sort_reverse else "ascending"
        self.notify(f"Sorted {labels[column]} {direction}")

    def action_generate(self) -> None:
        prompt = self.query_one("#prompt-input", TextArea).text
        if not prompt:
            self.notify("Enter a prompt first.", severity="warning")
            return
        if len(prompt.encode("utf-8")) > 100_000:
            self.notify("Prompt exceeds the 100 KB default limit.", severity="error")
            return
        profile = str(self.query_one("#profile", Select).value)
        intensity = str(self.query_one("#intensity", Select).value)
        count = int(self.query_one("#case-count", Select).value)
        pipelines: tuple[tuple[str, ...], ...] = ()
        if profile == "custom":
            selected = tuple(
                self.query_one("#custom-technique-list", SelectionList).selected
            )
            if not selected:
                self.notify("Select at least one custom technique.", severity="warning")
                return
            techniques = selected
            min_chain_length = 1
            max_chain_length = 1
            profile_config = {
                "name": "custom",
                "version": 1,
                "techniques": list(selected),
                "count": count,
                "intensity": intensity,
                "min_chain_length": 1,
                "max_chain_length": 1,
                "source": "tui-session",
            }
        elif profile == "custom_chain":
            chain = tuple(
                str(value)
                for step in range(1, 4)
                if (value := self.query_one(f"#chain-step-{step}", Select).value)
                is not Select.BLANK
            )
            first = self.query_one("#chain-step-1", Select).value
            second = self.query_one("#chain-step-2", Select).value
            if first is Select.BLANK or second is Select.BLANK:
                self.notify("Choose techniques for chain steps 1 and 2.", severity="warning")
                return
            techniques = chain
            pipelines = (chain,)
            min_chain_length = len(chain)
            max_chain_length = len(chain)
            profile_config = {
                "name": "custom_chain",
                "version": 1,
                "techniques": list(chain),
                "pipelines": [list(chain)],
                "count": count,
                "intensity": intensity,
                "min_chain_length": len(chain),
                "max_chain_length": len(chain),
                "source": "tui-session",
            }
        else:
            resolved_profile = load_profile(profile)
            techniques = resolved_profile.techniques
            min_chain_length = resolved_profile.min_chain_length
            max_chain_length = resolved_profile.max_chain_length
            profile_config = resolved_profile.resolved()
        projected_bytes = count * (len(prompt.encode("utf-8")) * 10 + 800)
        if projected_bytes > 250 * 1024 * 1024:
            self.notify(
                f"Projected bundle is {projected_bytes / 1024 / 1024:.1f} MB; reduce the prompt or case count.",
                severity="error",
            )
            return
        request = GenerationRequest(
            prompt=prompt,
            techniques=techniques,
            pipelines=pipelines,
            count=count,
            seed=0,
            intensity=intensity,
            min_chain_length=min_chain_length,
            max_chain_length=max_chain_length,
            profile=profile,
            profile_config=profile_config,
        )
        self.result = PromptGenerator().generate(request)
        bundle = AuditBundle.write(self.runs_root, request, self.result)
        table = self.query_one("#cases", DataTable)
        table.clear()
        for case in self.result.cases:
            preview = case.text.encode("unicode_escape").decode("ascii")[:72]
            table.add_row(
                f"case-{case.id[:8]}",
                " → ".join(case.techniques),
                preview,
                key=case.id,
            )
        self._sort_column = "technique"
        self._sort_reverse = False
        technique_key = next(
            key for key in table.columns if key.value == "technique"
        )
        table.sort(technique_key, key=lambda value: str(value).casefold())
        table.columns[technique_key].label = Text("Technique ▲")
        if self.result.cases:
            table.move_cursor(row=0)
            first_key = table.coordinate_to_cell_key(Coordinate(0, 0)).row_key
            self._select_case_id(str(first_key.value))
            self.query_one("#copy-raw", Button).disabled = False
            self.query_one("#copy-escaped", Button).disabled = False
        self.notify(f"Generated {len(self.result.cases)} cases. Audit: {bundle.path}")

    def action_copy_raw(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        self._copy(case.text, f"Copied case-{case.id[:8]} raw ({len(case.text)} characters)")

    def action_copy_escaped(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        escaped = case.text.encode("unicode_escape").decode("ascii")
        self._copy(escaped, f"Copied case-{case.id[:8]} escaped")

    def action_clear_clipboard(self) -> None:
        self._copy("", "Clipboard cleared")

    def action_select_all_techniques(self) -> None:
        self.query_one("#custom-technique-list", SelectionList).select_all()

    def action_clear_techniques(self) -> None:
        self.query_one("#custom-technique-list", SelectionList).deselect_all()

    def action_toggle_cases_maximized(self) -> None:
        section = self.query_one("#cases-section")
        if self.screen.maximized is section:
            self.screen.minimize()
        else:
            if self.screen.maximized is not None:
                self.screen.minimize()
            self.screen.maximize(section, container=False)

    def _sync_cases_maximize_button(self, maximized: object | None) -> None:
        section = self.query_one("#cases-section")
        button = self.query_one("#toggle-cases-maximized", Button)
        is_maximized = maximized is section
        button.label = "−" if is_maximized else "+"
        button.tooltip = (
            "Restore normal layout (Ctrl+M)"
            if is_maximized
            else "Maximize Generated Cases (Ctrl+M)"
        )

    @staticmethod
    def _default_config_root() -> Path:
        try:
            from platformdirs import user_config_path

            return Path(user_config_path("prompt-mutator", appauthor=False))
        except ImportError:
            return Path.home() / ".config" / "prompt-mutator"

    def _load_saved_theme(self) -> str | None:
        try:
            settings = json.loads(
                (self.config_root / "settings.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        theme = settings.get("theme") if isinstance(settings, dict) else None
        return theme if isinstance(theme, str) else None

    def _save_theme(self, theme: object) -> None:
        theme_name = getattr(theme, "name", None)
        if not isinstance(theme_name, str):
            return
        try:
            self.config_root.mkdir(parents=True, exist_ok=True)
            settings_path = self.config_root / "settings.json"
            settings: dict[str, object] = {}
            if settings_path.is_file():
                try:
                    loaded = json.loads(settings_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        settings.update(loaded)
                except (OSError, json.JSONDecodeError):
                    pass
            settings["theme"] = theme_name
            pending = settings_path.with_suffix(".tmp")
            pending.write_text(
                json.dumps(settings, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            pending.replace(settings_path)
        except OSError:
            # A read-only config directory should not prevent the TUI from running.
            return

    def _copy(self, text: str, message: str) -> None:
        try:
            self._clipboard_writer(text)
        except Exception as exc:  # Clipboard backends vary by operating system.
            self.notify(f"Clipboard unavailable: {exc}", severity="error")
            return
        self.notify(message)

    def _show_selected(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        escaped = case.text.encode("unicode_escape").decode("ascii")
        noteworthy = []
        seen: set[str] = set()
        for character in case.text:
            if character in seen:
                continue
            category = unicodedata.category(character)
            if ord(character) > 127 or category.startswith("C") or unicodedata.combining(character):
                seen.add(character)
                noteworthy.append(
                    f"U+{ord(character):04X} {unicodedata.name(character, 'UNNAMED')} ({category})"
                )
        code_points = "\n".join(noteworthy) if noteworthy else "No non-ASCII or invisible code points."
        summary = [
            f"case-{case.id[:8]}",
            f"Technique: {' → '.join(case.techniques)}",
        ]
        if "variant" in case.parameters:
            summary.append(f"Variant: {case.parameters['variant']}")
        summary.append(
            f"Changed source positions: {', '.join(map(str, case.changed_positions))}"
        )
        details = (
            "\n".join(summary)
            + f"\n\nRendered:\n{case.text}\n\n"
            + f"Escaped:\n{escaped}\n\n"
            + f"Code points:\n{code_points}"
        )
        self.query_one("#case-detail", Static).update(details)
        self.query_one("#case-detail-scroll", VerticalScroll).scroll_home(animate=False)
        self.sub_title = f"case-{case.id[:8]} • {len(case.text)} characters"

    def _select_case_id(self, case_id: str) -> None:
        if self.result is None:
            return
        for index, case in enumerate(self.result.cases):
            if case.id == case_id:
                self._selected_index = index
                self._show_selected()
                return

    def _selected_case(self):
        if self.result is None or not self.result.cases:
            return None
        return self.result.cases[self._selected_index]

def run_tui() -> None:
    PromptMutatorApp().run()
