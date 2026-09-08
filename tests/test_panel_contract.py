from pathlib import Path
import json
import shutil
import subprocess
import unittest


PANEL = (Path(__file__).parents[1] / "Panel.qml").read_text(encoding="utf-8")


class PanelContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is needed to exercise QML JavaScript")
    def test_folder_picker_preserves_settings_on_selection_and_cancel(self) -> None:
        def function(name):
            body = PANEL.split("  function " + name, 1)[1].split("\n  function ", 1)[0]
            return "function " + name + body

        functions = "\n".join(function(name) for name in (
            "browseProfilesRoot", "finishFolderPicker", "expandedProfilesPath"
        ))
        opened_handler = PANEL.split("  onOpenedChanged: {", 1)[1].split("\n  Timer {", 1)[0]
        opened_handler = opened_handler.rsplit("}", 1)[0]
        program = r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const functions = FUNCTIONS;
const openedHandler = HANDLER;
for (const provider of ['codex', 'claude-single', 'claude-multiple']) {
  for (const result of ['/selected/profile\n', '']) {
    const field = () => ({text: '/draft/profile', selectAll() {}, forceActiveFocus() {this.focused = true;}});
    const pending = [];
    const state = {
      folderPickerProcess: {running: false}, folderPickerActive: false,
      folderPickerTarget: '', folderPickerPath: '/plugin/folder_picker.py', home: '/home/test',
      codexProfilesRoot: '/saved/codex', claudeProfileRoot: '/saved/claude', claudeProfilesRoot: '/saved/multiple',
      codexProfilesRootField: field(), claudeProfileRootField: field(), claudeProfilesRootField: field(),
      editingSettings: true, editingProfileId: '', opened: true, draftPrivacyModeEnabled: false,
      Qt: {callLater(fn) {pending.push(fn);}}, hoverRefresh() {},
      keyCatcher: {forceActiveFocus() {}}, closeSettings() {state.editingSettings = false;},
      cancelProfileNameEdit() {},
    };
    const context = vm.createContext(state);
    state.close = () => {state.opened = false; vm.runInContext(openedHandler, context);};
    state.open = () => {state.opened = true; vm.runInContext(openedHandler, context);};
    vm.runInContext(functions, context);
    state.browseProfilesRoot(provider);
    assert.equal(state.opened, false);
    assert.equal(state.editingSettings, true);
    state.folderPickerProcess.running = false;
    state.finishFolderPicker(result);
    pending.forEach(fn => fn());
    const target = provider === 'codex' ? state.codexProfilesRootField
      : provider === 'claude-single' ? state.claudeProfileRootField : state.claudeProfilesRootField;
    assert.equal(target.text, result ? '/selected/profile' : '/draft/profile');
    assert.equal(state.opened, true);
    assert.equal(state.editingSettings, true);
    assert.equal(state.folderPickerActive, false);
    assert.equal(state.draftPrivacyModeEnabled, false);
    assert.equal(target.focused, true);
    state.close();
    assert.equal(state.editingSettings, false);
  }
}
'''.replace("FUNCTIONS", json.dumps(functions)).replace("HANDLER", json.dumps(opened_handler))
        subprocess.run([shutil.which("node"), "-e", program], check=True, capture_output=True, timeout=5)

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

    def test_claude_capture_requires_explicit_action(self) -> None:
        self.assertIn('onClicked: root.setupClaudeCapture(false)', PANEL)
        self.assertIn('onClicked: root.setupClaudeCapture(true)', PANEL)
        self.assertIn('--remove-claude-capture', PANEL)
        self.assertIn('"--setup-claude-capture", "--json"', PANEL)
        self.assertIn('Save Claude profile changes before changing capture.', PANEL)
        refresh = PANEL.split('function refreshNow(', 1)[1].split('function hoverRefresh(', 1)[0]
        self.assertNotIn('--setup-claude-capture', refresh)

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
