"""Regression guard for responsive WeatherRouter routing diagnostics."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = (
    ROOT
    / "custom_components"
    / "weather_router"
    / "frontend"
    / "weather-router-lab-routing-diagnostics.js"
)


class RoutingDiagnosticsResponsiveTest(unittest.TestCase):
    """Keep tablet and mobile diagnostics inside the viewport."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = FRONTEND.read_text(encoding="utf-8")

    def test_tablet_breakpoint_covers_ipad_landscape(self) -> None:
        self.assertIn("@media(max-width:1200px)", self.source)
        self.assertIn(
            ".wr-rd-manual-grid{grid-template-columns:repeat(2,minmax(0,1fr))}",
            self.source,
        )

    def test_outer_body_cannot_expand_horizontally(self) -> None:
        self.assertIn(
            ".wr-rd-body{overflow-y:auto;overflow-x:hidden",
            self.source,
        )
        self.assertIn(
            ".wr-rd-window,.wr-rd-window *{box-sizing:border-box}",
            self.source,
        )
        self.assertIn(
            ".wr-rd-body>*",
            self.source,
        )

    def test_form_controls_and_pre_blocks_are_width_bounded(self) -> None:
        self.assertIn(
            '.wr-rd-manual-grid input:not([type="checkbox"]):not([type="radio"]),.wr-rd-manual-grid select',
            self.source,
        )
        self.assertIn(
            "width:100%;min-width:0;max-width:100%",
            self.source,
        )
        self.assertIn(
            ".wr-rd-pre{width:100%;max-width:100%;min-width:0",
            self.source,
        )

    def test_mobile_header_actions_stay_compact_and_scrollable(self) -> None:
        self.assertIn(
            ".wr-rd-head-actions{grid-column:1/-1;grid-row:2;display:flex;gap:6px;flex-wrap:nowrap;",
            self.source,
        )
        self.assertIn(
            "justify-content:flex-start;align-items:center;align-self:start",
            self.source,
        )
        self.assertIn(
            "overflow-x:auto;overflow-y:hidden",
            self.source,
        )
        self.assertIn(
            ".wr-rd-head-actions button{flex:0 0 auto;width:auto;min-width:max-content;max-width:none;height:36px;min-height:36px;max-height:36px;",
            self.source,
        )
        self.assertNotIn(
            ".wr-rd-head-actions{grid-template-columns:1fr}",
            self.source,
        )

    def test_mobile_header_actions_reset_tablet_stretch(self) -> None:
        self.assertIn(
            "grid-template-rows:auto auto;align-items:start;align-content:start",
            self.source,
        )
        self.assertIn(
            "justify-content:flex-start;align-items:center;align-self:start;width:100%;height:42px;min-height:42px;max-height:42px;",
            self.source,
        )
        self.assertIn(
            "height:36px;min-height:36px;max-height:36px;",
            self.source,
        )

    def test_checkboxes_never_inherit_full_width_form_rules(self) -> None:
        self.assertIn(
            '.wr-rd-window input[type="checkbox"],.wr-rd-window input[type="radio"]{',
            self.source,
        )
        self.assertIn(
            "width:18px;height:18px;min-width:18px;max-width:18px;min-height:18px;max-height:18px;",
            self.source,
        )
        self.assertIn(
            '.wr-rd-toolbar input[type="checkbox"],.wr-rd-manual-grid input[type="checkbox"]{',
            self.source,
        )
        self.assertIn(
            "width:20px;height:20px;min-width:20px;max-width:20px;min-height:20px;max-height:20px;",
            self.source,
        )


    def test_git_export_is_first_quick_action_and_marks_current_trace(self) -> None:
        git_pos = self.source.index('id="wr-rd-head-git"')
        copy_pos = self.source.index('id="wr-rd-head-copy"')
        json_pos = self.source.index('id="wr-rd-head-json"')
        self.assertLess(git_pos, copy_pos)
        self.assertLess(git_pos, json_pos)
        self.assertIn('?"✓ In Git"', self.source)
        self.assertIn('wr-rd-git-exported', self.source)
        self.assertIn('state.gitExportedTraceId===currentTraceId', self.source)


if __name__ == "__main__":
    unittest.main()
