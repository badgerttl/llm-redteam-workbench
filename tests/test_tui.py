from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from textual.containers import Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.widgets import Collapsible, DataTable, Label, Select, SelectionList, TextArea

from prompt_mutator.audit import AuditBundle
from prompt_mutator.tui import PromptMutatorApp


class TuiContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_theme_is_restored_on_next_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = PromptMutatorApp(runs_root=root / "runs", config_root=root / "config")
            async with app.run_test() as pilot:
                app.theme = "textual-light"
                await pilot.pause()

            settings = json.loads(
                (root / "config" / "settings.json").read_text(encoding="utf-8")
            )
            self.assertEqual(settings["theme"], "textual-light")

            restored = PromptMutatorApp(
                runs_root=root / "runs",
                config_root=root / "config",
            )
            async with restored.run_test():
                self.assertEqual(restored.theme, "textual-light")

    async def test_generated_cases_can_maximize_and_restore_from_button_or_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(
                runs_root=Path(directory) / "runs",
                config_root=Path(directory) / "config",
            )
            async with app.run_test(size=(120, 50)) as pilot:
                section = app.query_one("#cases-section")
                button = app.query_one("#toggle-cases-maximized")

                await pilot.click("#toggle-cases-maximized")
                await pilot.pause()
                self.assertIs(app.screen.maximized, section)
                self.assertEqual(str(button.label), "−")

                await pilot.press("ctrl+m")
                await pilot.pause()
                self.assertIsNone(app.screen.maximized)
                self.assertEqual(str(button.label), "+")

                await pilot.press("ctrl+m")
                await pilot.pause()
                self.assertIs(app.screen.maximized, section)

                await pilot.click("#toggle-cases-maximized")
                await pilot.pause()
                self.assertIsNone(app.screen.maximized)

    async def test_user_can_generate_inspect_and_copy_a_raw_case(self) -> None:
        copied: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(
                runs_root=Path(directory),
                clipboard=copied.append,
            )
            async with app.run_test() as pilot:
                app.query_one("#prompt-input", TextArea).text = "Test this café prompt"
                await pilot.click("#generate")
                await pilot.pause()

                table = app.query_one("#cases", DataTable)
                self.assertEqual(table.row_count, 25)
                await pilot.click("#copy-raw")
                selected_id = table.coordinate_to_cell_key(Coordinate(0, 0)).row_key.value
                expected = next(case.text for case in app.result.cases if case.id == selected_id)
                self.assertEqual(copied[-1], expected)
                self.assertIn("case-", app.sub_title)

                zero_width_case = next(
                    case
                    for case in app.result.cases
                    if case.techniques == ("zero_width",)
                )
                table.move_cursor(row=table.get_row_index(zero_width_case.id))
                await pilot.pause()
                detail = str(app.query_one("#case-detail").render())
                self.assertIn("U+200B ZERO WIDTH SPACE", detail)

            bundles = [path for path in Path(directory).iterdir() if path.is_dir()]
            self.assertEqual(len(bundles), 1)

    async def test_default_clipboard_needs_no_external_linux_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(runs_root=Path(directory))
            async with app.run_test() as pilot:
                app.query_one("#prompt-input", TextArea).text = "Copy this prompt"
                await pilot.click("#generate")
                await pilot.click("#copy-raw")
                await pilot.pause()

                table = app.query_one("#cases", DataTable)
                selected_id = table.coordinate_to_cell_key(Coordinate(0, 0)).row_key.value
                expected = next(case.text for case in app.result.cases if case.id == selected_id)
                self.assertEqual(app.clipboard, expected)

    async def test_case_inspection_has_an_independent_scroll_area(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(runs_root=Path(directory))
            async with app.run_test(size=(100, 30)) as pilot:
                detail = app.query_one("#case-detail")
                detail.update("\n".join(f"Inspection line {line}" for line in range(80)))
                await pilot.pause()

                scroller = app.query_one("#case-detail-scroll", VerticalScroll)
                self.assertTrue(scroller.can_focus)
                self.assertGreater(scroller.max_scroll_y, 0)
                copy_button_region = app.query_one("#copy-raw").region
                scroller.focus()
                await pilot.press("pagedown")
                await pilot.pause()
                self.assertGreater(scroller.scroll_y, 0)
                self.assertEqual(app.query_one("#copy-raw").region, copy_button_region)

    async def test_layout_is_vertical_and_case_count_scales(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(runs_root=Path(directory))
            async with app.run_test(size=(160, 60)) as pilot:
                self.assertIsInstance(app.query_one("#workspace"), Vertical)
                labels = {str(label.render()) for label in app.query(".field-label")}
                self.assertEqual(labels, {"Profile", "Intensity", "Cases"})
                self.assertEqual(app.query_one("#prompt-input").region.height, 10)
                self.assertGreaterEqual(app.query_one("#profile").region.width, 24)
                self.assertGreaterEqual(app.query_one("#case-count").region.width, 14)
                count = app.query_one("#case-count", Select)
                self.assertEqual(count.value, 25)

                count.value = 50
                app.query_one("#prompt-input", TextArea).text = "Scale this café prompt"
                await pilot.click("#generate")
                await pilot.pause()

                self.assertEqual(app.query_one("#cases", DataTable).row_count, 50)
                unicode_name_case = next(
                    case
                    for case in app.result.cases
                    if case.parameters.get("variant") == "unicode-name"
                )
                table = app.query_one("#cases", DataTable)
                table.move_cursor(row=table.get_row_index(unicode_name_case.id))
                await pilot.pause()
                self.assertIn(
                    "Variant: unicode-name",
                    str(app.query_one("#case-detail").render()),
                )

    async def test_case_headers_toggle_sort_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(runs_root=Path(directory))
            async with app.run_test(size=(120, 50)) as pilot:
                app.query_one("#prompt-input", TextArea).text = "Sort this café prompt"
                await pilot.click("#generate")
                await pilot.pause()
                table = app.query_one("#cases", DataTable)
                technique_key = next(
                    key for key in table.columns if key.value == "technique"
                )
                self.assertEqual(table.get_row_at(0)[1], "base64")
                self.assertIn("▲", table.columns[technique_key].label.plain)

                table.post_message(
                    DataTable.HeaderSelected(
                        table,
                        technique_key,
                        1,
                        table.columns[technique_key].label,
                    )
                )
                await pilot.pause()
                self.assertEqual(table.get_row_at(0)[1], "zero_width")
                self.assertIn("▼", table.columns[technique_key].label.plain)
                self.assertIn(
                    "Technique: zero_width",
                    str(app.query_one("#case-detail").render()),
                )

                table.post_message(
                    DataTable.HeaderSelected(
                        table,
                        technique_key,
                        1,
                        table.columns[technique_key].label,
                    )
                )
                await pilot.pause()
                self.assertEqual(table.get_row_at(0)[1], "base64")
                self.assertIn("▲", table.columns[technique_key].label.plain)

    async def test_custom_profile_generates_only_selected_techniques(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(runs_root=Path(directory))
            async with app.run_test(size=(120, 60)) as pilot:
                app.query_one("#profile", Select).value = "custom"
                await pilot.pause()
                picker = app.query_one("#custom-technique-list", SelectionList)
                self.assertEqual(app.query_one("#custom-techniques").styles.display, "block")

                picker.deselect_all()
                picker.select("hex")
                picker.select("url")
                app.query_one("#prompt-input", TextArea).text = "Customize this prompt"
                await pilot.click("#generate")
                await pilot.pause()

                self.assertTrue(app.result.cases)
                self.assertTrue(
                    all(set(case.techniques) <= {"hex", "url"} for case in app.result.cases)
                )
                bundle = next(path for path in Path(directory).iterdir() if path.is_dir())
                request, _ = AuditBundle.load(bundle)
                self.assertEqual(request.profile, "custom")
                self.assertEqual(request.techniques, ("hex", "url"))

    async def test_chained_profile_generates_only_multi_technique_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(runs_root=Path(directory))
            async with app.run_test(size=(120, 50)) as pilot:
                app.query_one("#profile", Select).value = "chained"
                app.query_one("#prompt-input", TextArea).text = "Chain this café prompt"
                await pilot.click("#generate")
                await pilot.pause()

                self.assertEqual(len(app.result.cases), 25)
                self.assertTrue(
                    all(2 <= len(case.techniques) <= 3 for case in app.result.cases)
                )

    async def test_custom_chain_uses_exactly_two_or_three_ordered_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = PromptMutatorApp(runs_root=Path(directory))
            async with app.run_test(size=(140, 60)) as pilot:
                app.query_one("#profile", Select).value = "custom_chain"
                await pilot.pause()
                panel = app.query_one("#custom-chain", Collapsible)
                self.assertEqual(panel.styles.display, "block")
                self.assertFalse(panel.collapsed)

                app.query_one("#chain-step-1", Select).value = "leetspeak"
                app.query_one("#chain-step-2", Select).value = "homoglyph"
                app.query_one("#chain-step-3", Select).value = "hex"
                app.query_one("#prompt-input", TextArea).text = "Use this exact chain"
                await pilot.click("#generate")
                await pilot.pause()
                self.assertTrue(app.result.cases)
                self.assertTrue(
                    all(
                        case.techniques == ("leetspeak", "homoglyph", "hex")
                        for case in app.result.cases
                    )
                )

                app.query_one("#chain-step-3", Select).clear()
                await pilot.click("#generate")
                await pilot.pause()
                self.assertTrue(
                    all(
                        case.techniques == ("leetspeak", "homoglyph")
                        for case in app.result.cases
                    )
                )


if __name__ == "__main__":
    unittest.main()
