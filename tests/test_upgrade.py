"""Run with python -m unittest discover -s tests -p test_upgrade.py.

All subprocesses, including curl and pip, are mocked.
"""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "upgrade_under_test", Path(__file__).resolve().parents[1] / "digie35/upgrade.py")
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class UpgradeTests(unittest.TestCase):
    def simulate(self, installed, available, *args, fail_install=False):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            output = ""
            code = 0
            if command[:4] == [sys.executable, "-m", "pip", "show"]:
                output = "Version: " + installed + "\n"
            elif command[0] == "curl":
                output = "\n".join(f'<a href="digie35_ctrl-{v}-py3-none-any.whl">wheel</a>' for v in available)
            elif command[:4] == [sys.executable, "-m", "pip", "install"]:
                code = 1 if fail_install else 0
            return SimpleNamespace(returncode=code, stdout=output.encode(), stderr=b"test failure" if code else b"")
        with patch.object(sys, "argv", ["digie35_upgrade", *args]), patch.object(upgrade.subprocess, "run", run), patch.object(upgrade.locale, "setlocale"):
            try:
                upgrade.main()
                status = 0
            except SystemExit as exc:
                status = exc.code
        return calls, status

    def install_commands(self, calls):
        return [c for c in calls if c[:4] == [sys.executable, "-m", "pip", "install"]]

    def test_latest_patch_independent_of_listing_order(self):
        for versions in (["0.8.1", "0.8.3", "0.8.2"], ["0.8.2", "0.8.1", "0.8.3"]):
            calls, status = self.simulate("0.8.1", versions)
            self.assertEqual(status, 0)
            self.assertTrue(self.install_commands(calls)[0][-1].endswith("0.8.3-py3-none-any.whl"))
            self.assertEqual(calls[-1][:3], [sys.executable, "-m", "digie35.install"])

    def test_major_versions(self):
        calls, status = self.simulate("1.0.0", ["2.3.0", "10.2.0", "9.0.0"])
        self.assertEqual(status, 0)
        self.assertTrue(self.install_commands(calls)[0][-1].endswith("10.2.0-py3-none-any.whl"))

    def test_exact_release(self):
        calls, status = self.simulate("0.8.1", ["0.8.1", "0.8.2", "0.8.3"], "--release", "0.8.2")
        self.assertEqual(status, 0)
        self.assertTrue(self.install_commands(calls)[0][-1].endswith("0.8.2-py3-none-any.whl"))

    def test_no_automatic_downgrade_even_with_force(self):
        for args in ([], ["--force"]):
            calls, status = self.simulate("0.9.0", ["0.8.1"], *args)
            self.assertEqual(status, 0)
            self.assertFalse(self.install_commands(calls))

    def test_explicit_downgrade(self):
        calls, status = self.simulate("0.9.0", ["0.8.1"], "--release", "0.8.1")
        self.assertEqual(status, 0)
        self.assertEqual(len(self.install_commands(calls)), 1)

    def test_same_version_requires_force(self):
        for args in ([], ["--force"]):
            calls, status = self.simulate("0.8.1", ["0.8.1"], *args)
            self.assertEqual(status, 0)
            self.assertEqual(bool(self.install_commands(calls)), bool(args))

    def test_dry_run_does_not_reconfigure_services(self):
        calls, status = self.simulate("0.8.1", ["0.8.2"], "--dry_run")
        self.assertEqual(status, 0)
        self.assertIn("--dry-run", self.install_commands(calls)[0])
        self.assertFalse(any("digie35.install" in c for c in calls))

    def test_failed_pip_does_not_reconfigure_services(self):
        calls, status = self.simulate("0.8.1", ["0.8.2"], fail_install=True)
        self.assertNotEqual(status, 0)
        self.assertFalse(any("digie35.install" in c for c in calls))

    def test_check_does_not_install(self):
        calls, status = self.simulate("0.8.1", ["0.8.2"], "--check")
        self.assertEqual(status, 0)
        self.assertFalse(self.install_commands(calls))

    def test_missing_exact_release_does_not_install(self):
        calls, status = self.simulate("0.8.1", ["0.8.1", "0.8.3"], "--release", "0.8.2")
        self.assertEqual(status, 2)
        self.assertFalse(self.install_commands(calls))


if __name__ == "__main__":
    unittest.main()
