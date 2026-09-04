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


if __name__ == "__main__":
    unittest.main()
