"""Focused private-environment assembly checks (no production credentials)."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "ip_cutover_env.py"
spec = importlib.util.spec_from_file_location("ip_cutover_env", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CutoverEnvironmentTest(unittest.TestCase):
    def test_rejects_duplicate_and_multiline_values_without_echoing_secret(self):
        for lines in (["ATOM_SECRET=private", "ATOM_SECRET=private"],
                      ["ATOM_SECRET=private\nexposed"]):
            with self.subTest(lines=lines), self.assertRaises(module.EnvironmentError) as caught:
                module._read_pairs(lines)
            self.assertNotIn("private", str(caught.exception))

    def test_private_write_excludes_secret_from_output_and_blocks_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "api.env"
            module._write_private(path, {"ATOM_SECRET": "test-private-value",
                                         "ATOM_STORAGE_BACKEND": "cos"})
            self.assertEqual(path.read_text(encoding="utf-8").splitlines(),
                             ["ATOM_SECRET=test-private-value", "ATOM_STORAGE_BACKEND=cos"])
            with self.assertRaises(FileExistsError):
                module._write_private(path, {"ATOM_SECRET": "other"})
            self.assertIn("test-private-value", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
