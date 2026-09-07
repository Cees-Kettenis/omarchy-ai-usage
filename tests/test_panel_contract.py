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
        self.assertIn('text: "OPENAI"', PANEL)
        self.assertIn('text: "Refresh"', PANEL)
        self.assertIn('text: "Interval (min)"', PANEL)
        self.assertIn('text: "Cooldown (sec)"', PANEL)
        self.assertIn("OpenAI refresh settings do not request Claude usage", PANEL)

    def test_hover_cooldown_is_inline_with_refresh_controls(self) -> None:
        controls_start = PANEL.index("id: refreshControls")
        controls_end = PANEL.index('label: "Pause scheduled checks"')
        cooldown_position = PANEL.index("id: hoverCooldownField")
        self.assertLess(controls_start, cooldown_position)
        self.assertLess(cooldown_position, controls_end)
        self.assertIn("readonly property int secondaryCount", PANEL)

    def test_sleep_schedule_is_part_of_openai_settings(self) -> None:
        sleep_position = PANEL.index('label: "Pause scheduled checks"')
        claude_position = PANEL.index('text: "CLAUDE"')
        self.assertLess(sleep_position, claude_position)
        self.assertIn("Only affects OpenAI", PANEL)

    def test_privacy_header_and_settings_actions_are_consistent(self) -> None:
        self.assertIn('text: "PRIVACY"', PANEL)
        self.assertEqual(PANEL.count("width: settingsActions.actionWidth"), 2)
        self.assertEqual(PANEL.count("height: settingsActions.actionHeight"), 2)

    def test_settings_controls_share_a_height(self) -> None:
        self.assertIn("readonly property real controlHeight", PANEL)
        self.assertGreaterEqual(PANEL.count("settingsColumn.controlHeight"), 11)
        self.assertIn("field.height: settingsColumn.controlHeight", PANEL)

    def test_claude_capture_is_automatic(self) -> None:
        self.assertIn("configures Claude Code's official status line automatically", PANEL)
        self.assertNotIn("installClaudeBridge", PANEL)
        self.assertNotIn("claudeBridgeProcess", PANEL)
        self.assertNotIn("Set up Claude usage", PANEL)

    def test_summary_header_is_compact(self) -> None:
        self.assertEqual(PANEL.count('text: "󱚣"'), 1)
        self.assertNotIn('? "AI usage"', PANEL)
        self.assertLess(PANEL.index("id: settingsButton"), PANEL.index("id: settingsColumn"))
        repeater_position = PANEL.index("model: root.accounts", PANEL.index("id: viewSwitch"))
        self.assertLess(repeater_position, PANEL.index("id: settingsButton"))

    def test_redundant_summary_headers_are_removed(self) -> None:
        self.assertNotIn("Preferred limit for every provider profile", PANEL)
        self.assertNotIn('text: "USAGE LEFT"', PANEL)
        self.assertNotIn('text: "LIMITS"', PANEL)
        self.assertNotIn('text: "CREDITS"', PANEL)
        self.assertIn("Sleep mode · OpenAI checks paused", PANEL)
        self.assertNotIn("Scheduled OpenAI checks paused ", PANEL)


if __name__ == "__main__":
    unittest.main()
