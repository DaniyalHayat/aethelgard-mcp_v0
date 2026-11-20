"""Atomic local artifacts with path confinement and content fingerprints."""

import hashlib
import json
import re
from pathlib import Path


class RunStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run identifier")
        path = self.root / run_id
        path.mkdir(exist_ok=True)
        return path

    def write(self, run_id, name, value):
        if not re.fullmatch(r"[a-z0-9_\-]+\.json", name):
            raise ValueError("Invalid artifact filename")
        target = self.directory(run_id) / name
        raw = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
        temporary = target.with_suffix(".tmp")
        payload = raw.encode("utf-8")
        temporary.write_bytes(payload)
        temporary.replace(target)
        return hashlib.sha256(payload).hexdigest()

    def read(self, run_id, name):
        if not re.fullmatch(r"[a-z0-9_\-]+\.json", name):
            raise ValueError("Invalid artifact filename")
        return json.loads((self.directory(run_id) / name).read_text(encoding="utf-8"))

    def recover(self):
        for directory in self.root.iterdir():
            status_file = directory / "status.json"
            if re.fullmatch(r"[a-f0-9]{32}", directory.name) and status_file.is_file():
                status = json.loads(status_file.read_text(encoding="utf-8"))
                if status.get("status") == "running":
                    status["status"] = "interrupted"
                    status["message"] = "Process ended before completion; start a new run to retry."
                    self.write(directory.name, "status.json", status)
