from __future__ import annotations

import base64
import gzip
import hashlib
import html
import json
import os
import platform
import shutil
import tempfile
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .models import GeneratedCase, GenerationRequest, RunResult


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    valid: bool
    mismatches: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuditBundle:
    path: Path

    @classmethod
    def write(
        cls,
        root: Path,
        request: GenerationRequest,
        result: RunResult,
    ) -> "AuditBundle":
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
        try:
            cls._write_files(pending, request, result)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            run_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
            final = root / run_id
            pending.replace(final)
            cls._restrict_permissions(final)
            return cls(final)
        except BaseException:
            shutil.rmtree(pending, ignore_errors=True)
            raise

    @classmethod
    def _write_files(
        cls,
        path: Path,
        request: GenerationRequest,
        result: RunResult,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        run = {
            "schema_version": SCHEMA_VERSION,
            "status": "completed-with-errors" if result.errors else "completed",
            "created_at": now,
            "tool": {"name": "llm-redteam-workbench", "version": __version__},
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "unicode": unicodedata.unidata_version,
            },
            "request": asdict(request),
            "summary": {
                "unique_cases": len(result.cases),
                "attempted": result.attempted,
                "skipped": len(result.skipped),
                "errors": len(result.errors),
            },
        }
        cls._write_json(path / "run.json", run)
        cls._write_jsonl(
            path / "inputs.jsonl",
            [{"schema_version": SCHEMA_VERSION, "id": "input-1", "prompt": request.prompt, "sha256": result.input_hash}],
        )
        with gzip.open(path / "cases.jsonl.gz", "wt", encoding="utf-8", newline="\n") as handle:
            for case in result.cases:
                record = asdict(case)
                record.update({"schema_version": SCHEMA_VERSION, "input_id": "input-1"})
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        cls._write_json(path / "diagnostics.json", {"skipped": result.skipped, "errors": result.errors})
        (path / "events.log").write_text(
            f"{now} run completed status={run['status']} cases={len(result.cases)}\n",
            encoding="utf-8",
        )
        (path / "report.html").write_text(cls._report(request, result), encoding="utf-8")
        manifest = {
            "algorithm": "sha256",
            "files": {
                item.name: cls._sha256(item)
                for item in sorted(path.iterdir())
                if item.is_file()
            },
        }
        cls._write_json(path / "manifest.json", manifest)

    @classmethod
    def load(cls, path: Path) -> tuple[GenerationRequest, RunResult]:
        path = Path(path)
        run = json.loads((path / "run.json").read_text(encoding="utf-8"))
        request_data = run["request"]
        request_data["techniques"] = tuple(request_data["techniques"])
        request_data["pipelines"] = tuple(
            tuple(pipeline) for pipeline in request_data.get("pipelines", ())
        )
        request = GenerationRequest(**request_data)
        input_record = json.loads((path / "inputs.jsonl").read_text(encoding="utf-8").splitlines()[0])
        cases: list[GeneratedCase] = []
        with gzip.open(path / "cases.jsonl.gz", "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                cases.append(
                    GeneratedCase(
                        id=record["id"],
                        text=record["text"],
                        techniques=tuple(record["techniques"]),
                        parameters=record["parameters"],
                        changed_positions=tuple(record["changed_positions"]),
                        producing_pipelines=tuple(tuple(p) for p in record["producing_pipelines"]),
                    )
                )
        diagnostics = json.loads((path / "diagnostics.json").read_text(encoding="utf-8"))
        result = RunResult(
            input_hash=input_record["sha256"],
            seed=request.seed,
            cases=tuple(cases),
            attempted=run["summary"]["attempted"],
            skipped=tuple(diagnostics["skipped"]),
            errors=tuple(diagnostics["errors"]),
        )
        return request, result

    @classmethod
    def verify(cls, path: Path) -> VerificationResult:
        path = Path(path)
        try:
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return VerificationResult(False, (f"manifest: {exc}",))
        mismatches = []
        declared = manifest.get("files", {})
        for name, expected in declared.items():
            candidate = path / name
            if not candidate.is_file():
                mismatches.append(f"missing:{name}")
            elif cls._sha256(candidate) != expected:
                mismatches.append(f"changed:{name}")
        actual = {item.name for item in path.iterdir() if item.is_file()}
        expected_names = set(declared) | {"manifest.json"}
        for name in sorted(actual - expected_names):
            mismatches.append(f"unexpected:{name}")
        return VerificationResult(not mismatches, tuple(mismatches))

    @classmethod
    def rebuild_report(cls, path: Path) -> Path:
        path = Path(path)
        request, result = cls.load(path)
        report_path = path / "report.html"
        report_path.write_text(cls._report(request, result), encoding="utf-8")
        return report_path

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
        path.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records), encoding="utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _restrict_permissions(path: Path) -> None:
        if os.name == "nt":
            return
        path.chmod(0o700)
        for item in path.iterdir():
            item.chmod(0o600)

    @staticmethod
    def _report(request: GenerationRequest, result: RunResult) -> str:
        rows = []
        for case in result.cases:
            escaped_text = html.escape(case.text.encode("unicode_escape").decode("ascii"))
            rows.append(
                "<tr><td><code>case-"
                + html.escape(case.id[:8])
                + "</code></td><td>"
                + html.escape(" → ".join(case.techniques))
                + "</td><td><code>"
                + escaped_text
                + "</code></td></tr>"
            )
        search_script = (
            'const q=document.getElementById("search");'
            'q.addEventListener("input",()=>{const v=q.value.toLowerCase();'
            'document.querySelectorAll("tbody tr").forEach(r=>'
            'r.hidden=!r.textContent.toLowerCase().includes(v));});'
        )
        script_hash = base64.b64encode(hashlib.sha256(search_script.encode("utf-8")).digest()).decode("ascii")
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-%s'">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LLM Red Team Workbench report</title>
<style>body{font-family:system-ui;margin:2rem;color:#18212b}table{border-collapse:collapse;width:100%%}th,td{border:1px solid #ccd5df;padding:.5rem;text-align:left;vertical-align:top}code{white-space:pre-wrap;overflow-wrap:anywhere}.summary{display:flex;gap:2rem}label{display:block;margin:1rem 0}input{font:inherit;padding:.5rem;width:min(36rem,90%%)}</style>
</head><body><h1>LLM Red Team Workbench report</h1>
<div class="summary"><p><strong>Cases:</strong> %d</p><p><strong>Seed:</strong> %d</p><p><strong>Profile:</strong> %s</p></div>
<p>Generation coverage only. Cases were not executed against an LLM.</p>
<label>Search cases <input id="search" type="search" autocomplete="off"></label>
<table><thead><tr><th>Case</th><th>Technique</th><th>Escaped prompt</th></tr></thead><tbody>%s</tbody></table>
<script>%s</script>
</body></html>""" % (
            script_hash,
            len(result.cases),
            request.seed,
            html.escape(request.profile),
            "".join(rows),
            search_script,
        )
