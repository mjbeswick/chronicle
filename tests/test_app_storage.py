from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.storage import ChronicleStorageAdapter


class ChronicleStorageAdapterTests(unittest.TestCase):
    def test_adapter_uses_chronicle_home_when_set(self) -> None:
        workspace = tempfile.mkdtemp(prefix="chronicle-home-")
        try:
            with patch.dict(os.environ, {"CHRONICLE_HOME": workspace}):
                adapter = ChronicleStorageAdapter()
            self.assertEqual(Path(workspace).resolve(), adapter.backend.project_root)
        finally:
            shutil.rmtree(workspace)


if __name__ == "__main__":
    unittest.main()
