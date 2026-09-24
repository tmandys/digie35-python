"""Installer control-flow tests. No real system commands are executed.

Run: python -m unittest discover -s tests -p test_install.py
"""
import importlib.util
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "digie35" / "install.py"
spec = importlib.util.spec_from_file_location("installer_under_test", SOURCE)
installer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = installer
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.calls = []
        self.failure = lambda command: 0
        self.gvfs_mode = 0o755
        self.stack.enter_context(patch.object(installer, "subprocess_run", self.execute))
        self.stack.enter_context(patch.object(installer.locale, "setlocale"))
        self.stack.enter_context(patch.object(installer.shutil, "which", lambda name: "/usr/bin/" + name))
        self.stack.enter_context(patch.object(installer.os.path, "expanduser", lambda path: str(self.temp / path[2:])))
        exists = installer.os.path.exists
        stat = installer.os.stat
        self.stack.enter_context(patch.object(installer.os.path, "exists", lambda path: True if str(path) == "/usr/lib/gvfs/gvfsd-gphoto2" else exists(path)))
        self.stack.enter_context(patch.object(installer.os, "stat", lambda path, *a, **kw: SimpleNamespace(st_mode=self.gvfs_mode) if str(path) == "/usr/lib/gvfs/gvfsd-gphoto2" else stat(path, *a, **kw)))

    def execute(self, command, **kwargs):
        self.calls.append(command)
        code = self.failure(command)
        if command[:2] == ["mkdir", "-p"] and code == 0:
            Path(command[2]).mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=code, stdout=b"inactive\n", stderr=b"simulated failure\n" if code else b"")

    def invoke(self, *args):
        with patch.object(sys, "argv", ["digie35_install", *args]):
            installer.main()

    def test_www_links_have_existing_sources_and_sound_directory(self):
        self.invoke("-i", "-w", "/var/www/html")
        links = [c for c in self.calls if c[:3] == ["sudo", "ln", "-s"]]
        self.assertTrue(links)
        for command in links:
            self.assertTrue(Path(command[3]).is_file(), command)
        mkdir = ["sudo", "mkdir", "-p", "/var/www/html/sounds"]
        sound = next(c for c in links if c[-1].endswith("/sounds/error.mp3"))
        self.assertLess(self.calls.index(mkdir), self.calls.index(sound))

    def test_copy_failure_stops_before_default_config_removal(self):
        self.failure = lambda c: 1 if c[:2] == ["sudo", "cp"] else 0
        with self.assertRaisesRegex(SystemExit, "Command failed.*sudo cp"):
            self.invoke("-i")
        self.assertNotIn(["sudo", "rm", "-f", "/etc/nginx/sites-enabled/default"], self.calls)
        self.assertNotIn(["sudo", "nginx", "-s", "reload"], self.calls)

    def test_bad_nginx_config_prevents_reload(self):
        self.failure = lambda c: 1 if c == ["sudo", "nginx", "-t"] else 0
        with self.assertRaisesRegex(SystemExit, "nginx -t"):
            self.invoke("-i")
        self.assertNotIn(["sudo", "nginx", "-s", "reload"], self.calls)

    def test_inactive_services_and_absent_process_are_expected(self):
        self.failure = lambda c: 3 if "is-active" in c else (1 if "killall" in c else 0)
        self.invoke("-i", "-r", "-w", "none")
        self.assertFalse(any("restart" in c for c in self.calls))

    def test_uninstall_removes_both_nginx_configs(self):
        self.invoke("-u")
        for name in ["digie35.conf", "ustreamer.conf"]:
            self.assertIn(["sudo", "rm", "-f", "/etc/nginx/conf.d/" + name], self.calls)
        self.assertLess(self.calls.index(["sudo", "nginx", "-t"]), self.calls.index(["sudo", "nginx", "-s", "reload"]))

    def test_reinstall_preserves_original_gvfs_mode(self):
        self.invoke("-i", "-w", "none")
        backup = self.temp / ".config/digie35/gvfsd-gphoto2.mode"
        self.assertEqual(backup.read_text(), "755")
        self.gvfs_mode = 0o644
        self.invoke("-i", "-w", "none")
        self.assertEqual(backup.read_text(), "755")
        self.invoke("-u", "-w", "none")
        self.assertIn(["sudo", "chmod", "755", "/usr/lib/gvfs/gvfsd-gphoto2"], self.calls)
        self.assertFalse(backup.exists())

    def test_failed_restore_keeps_backup(self):
        self.invoke("-i", "-w", "none")
        self.failure = lambda c: 1 if c[:3] == ["sudo", "chmod", "755"] else 0
        with self.assertRaises(SystemExit):
            self.invoke("-u", "-w", "none")
        self.assertTrue((self.temp / ".config/digie35/gvfsd-gphoto2.mode").exists())


if __name__ == "__main__":
    unittest.main()
