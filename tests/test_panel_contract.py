from pathlib import Path
import unittest


PANEL = (Path(__file__).parents[1] / "Panel.qml").read_text(encoding="utf-8")


class PanelContractTests(unittest.TestCase):
    def test_cache_is_read_through_collector(self) -> None:
        self.assertNotIn("FileView {", PANEL)
        self.assertIn('["--cached", "--json"]', PANEL)

    def test_processes_use_fixed_commands_and_deadlines(self) -> None:
        self.assertIn('"/usr/bin/python3"', PANEL)
        self.assertIn('"/usr/bin/timeout"', PANEL)
        self.assertIn('"--kill-after=2s"', PANEL)
        self.assertIn("Component.onDestruction", PANEL)

    def test_provider_roots_are_passed_separately(self) -> None:
        self.assertIn('"--codex-profiles-root", codexProfilesRoot', PANEL)
        self.assertIn('"--claude-profiles-root", claudeProfilesRoot', PANEL)

    def test_hover_refresh_has_a_configurable_cooldown(self) -> None:
        self.assertIn("function hoverRefresh()", PANEL)
        self.assertIn("hoverCooldownSec * 1000", PANEL)
        self.assertIn("onTooltipHoveredChanged", PANEL)

    def test_scheduled_timer_obeys_refresh_mode(self) -> None:
        self.assertIn("running: root.refreshOnSchedule", PANEL)


if __name__ == "__main__":
    unittest.main()
