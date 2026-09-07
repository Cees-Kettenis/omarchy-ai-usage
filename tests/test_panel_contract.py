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
        self.assertIn('"--claude-profiles-root", activeClaudeProfilesRoot', PANEL)
        self.assertIn('"--claude-profile-mode", claudeModeArgument(claudeProfileMode)', PANEL)

    def test_claude_defaults_to_single_account_and_keeps_multiple_location(self) -> None:
        self.assertIn('property string draftClaudeProfileMode: "Single account"', PANEL)
        self.assertIn('property string draftClaudeProfileRoot: "~/.claude"', PANEL)
        self.assertIn('property string draftClaudeProfilesRoot: "~/.claude-profiles"', PANEL)
        self.assertIn('options: ["Single account", "Multiple accounts"]', PANEL)

    def test_legacy_settings_are_migrated(self) -> None:
        self.assertIn("function migrateSettings()", PANEL)
        self.assertIn('values.codexProfilesRoot = String(setting("profilesRoot"', PANEL)
        self.assertIn('values.claudeProfileMode = "Single account"', PANEL)

    def test_profile_names_apply_to_summary_and_switcher(self) -> None:
        self.assertIn("function displayProfileName(value)", PANEL)
        self.assertIn("function beginProfileNameEdit(value)", PANEL)
        self.assertIn("function saveProfileName(value)", PANEL)
        self.assertIn('tooltipText: "Rename " + root.displayProfileName(modelData)', PANEL)
        self.assertNotIn("editingProfileNames", PANEL)
        self.assertGreaterEqual(PANEL.count("root.displayProfileName(modelData)"), 2)

    def test_hover_refresh_has_a_configurable_cooldown(self) -> None:
        self.assertIn("function hoverRefresh()", PANEL)
        self.assertIn("hoverCooldownSec * 1000", PANEL)
        self.assertIn("onTooltipHoveredChanged", PANEL)

    def test_scheduled_timer_obeys_refresh_mode(self) -> None:
        self.assertIn("running: root.refreshOnSchedule", PANEL)

    def test_refresh_settings_are_labeled_as_openai_only(self) -> None:
        self.assertIn('text: "OPENAI SETTINGS"', PANEL)
        self.assertIn('label: "API refresh behavior"', PANEL)
        self.assertIn('label: "Schedule interval (minutes)"', PANEL)
        self.assertIn("OpenAI refresh settings do not request Claude usage", PANEL)


if __name__ == "__main__":
    unittest.main()
