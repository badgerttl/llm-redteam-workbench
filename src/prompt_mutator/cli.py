from __future__ import annotations

import json
import math
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .audit import AuditBundle, SCHEMA_VERSION
from .generator import PromptGenerator
from .extensions import discover_extensions, load_extensions
from .models import GenerationRequest
from .profiles import available_profiles, load_profile


app = typer.Typer(
    name="llm-redteam",
    help="Generate deterministic prompt mutations for authorized internal testing.",
    no_args_is_help=False,
    invoke_without_command=True,
)
runs_app = typer.Typer(help="List, inspect, and delete retained audit runs.")
app.add_typer(runs_app, name="runs")


def default_runs_root() -> Path:
    try:
        from platformdirs import user_data_path

        return Path(user_data_path("prompt-mutator", appauthor=False)) / "runs"
    except ImportError:
        return Path.home() / ".local" / "share" / "prompt-mutator" / "runs"


@app.callback()
def main(ctx: typer.Context) -> None:
    """Launch the local web app when no automation subcommand is supplied."""
    if ctx.invoked_subcommand is None:
        _launch_web("127.0.0.1", 8765, (), open_browser=True)


@app.command()
def web(
    host: Annotated[str, typer.Option(help="Interface to bind; use 0.0.0.0 for remote review")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1024, max=65535)] = 8765,
    allowed_host: Annotated[
        list[str] | None,
        typer.Option("--allowed-host", help="Accepted Host header; repeat for multiple names"),
    ] = None,
    no_browser: Annotated[bool, typer.Option("--no-browser", is_flag=True)] = False,
) -> None:
    """Launch the local web interface."""
    _launch_web(host, port, tuple(allowed_host or ()), open_browser=not no_browser)


def _launch_web(
    host: str,
    port: int,
    allowed_hosts: tuple[str, ...],
    *,
    open_browser: bool,
) -> None:
    try:
        from .web import run_web
    except ImportError as exc:
        raise typer.ClickException(
            "The web UI requires the 'starlette' and 'uvicorn' dependencies."
        ) from exc
    try:
        run_web(
            host=host,
            port=port,
            allowed_hosts=allowed_hosts,
            open_browser=open_browser,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def tui() -> None:
    """Launch the terminal interface."""
    try:
        from .tui import run_tui
    except ImportError as exc:
        raise typer.ClickException(
            "The TUI requires the 'textual' dependency. Install LLM Red Team Workbench with its standard dependencies."
        ) from exc
    run_tui()


@app.command()
def generate(
    prompt: Annotated[str | None, typer.Argument(help="Prompt text; omit or use '-' to read stdin")] = None,
    count: Annotated[int | None, typer.Option(min=1, max=10_000)] = None,
    seed: Annotated[int, typer.Option()] = 0,
    intensity: Annotated[str | None, typer.Option(help="low, medium, high, or max")] = None,
    technique: Annotated[list[str] | None, typer.Option("--technique", "-t")] = None,
    profile: Annotated[str, typer.Option(help="Named built-in or custom profile")] = "baseline",
    profile_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    enable_extension: Annotated[list[str] | None, typer.Option("--enable-extension")] = None,
    all_cases: Annotated[bool, typer.Option("--all", help="Generate the bounded exhaustive catalog")] = False,
    override_limits: Annotated[bool, typer.Option("--override-limits", is_flag=True, help="Allow projected bundles above 250 MB")] = False,
    output_format: Annotated[str, typer.Option("--format", help="text or jsonl")] = "text",
    output: Annotated[Path | None, typer.Option(file_okay=False)] = None,
    no_history_warning: Annotated[bool, typer.Option("--no-history-warning", is_flag=True, help="Suppress the direct-argument sensitivity warning")] = False,
) -> None:
    """Generate variations and retain a complete local audit bundle."""
    direct_argument = prompt not in {None, "-"}
    if not direct_argument:
        prompt = sys.stdin.read()
    assert prompt is not None
    if direct_argument and not no_history_warning:
        typer.echo(
            "Warning: direct prompt arguments may appear in shell history; prefer stdin or the TUI for sensitive content.",
            err=True,
        )
    if len(prompt.encode("utf-8")) > 100_000:
        raise typer.BadParameter("prompt exceeds the 100 KB default limit")
    try:
        resolved_profile = load_profile(profile, profile_file)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        extension_transforms, extension_details = load_extensions(tuple(enable_extension or ()))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    generator = PromptGenerator(extension_transforms)
    selected = tuple(technique or resolved_profile.techniques)
    if technique is None:
        selected += tuple(extension_transforms)
    unknown = set(selected) - set(generator.available_techniques())
    if unknown:
        raise typer.BadParameter("unknown technique(s): " + ", ".join(sorted(unknown)))
    resolved_intensity = intensity or resolved_profile.intensity
    if resolved_intensity not in {"low", "medium", "high", "max"}:
        raise typer.BadParameter("intensity must be low, medium, high, or max")
    resolved_count = count or resolved_profile.count
    if all_cases:
        singles = len(selected) * 8 if resolved_profile.min_chain_length == 1 else 0
        chains = sum(
            math.perm(len(selected), length)
            for length in range(
                max(2, resolved_profile.min_chain_length),
                resolved_profile.max_chain_length + 1,
            )
        )
        resolved_count = min(10_000, singles + chains)
        typer.echo(f"Exhaustive projection: up to {resolved_count} unique cases", err=True)
    projected_bytes = resolved_count * (len(prompt.encode("utf-8")) * 10 + 800)
    soft_limit = 250 * 1024 * 1024
    hard_limit = 1024 * 1024 * 1024
    if projected_bytes > hard_limit or (projected_bytes > soft_limit and not override_limits):
        limit = "1 GB hard" if projected_bytes > hard_limit else "250 MB default"
        raise typer.BadParameter(
            f"projected bundle exceeds the {limit} limit ({projected_bytes / 1024 / 1024:.1f} MB)"
        )
    request = GenerationRequest(
        prompt=prompt,
        techniques=selected,
        count=resolved_count,
        seed=seed,
        intensity=resolved_intensity,
        min_chain_length=resolved_profile.min_chain_length,
        max_chain_length=resolved_profile.max_chain_length,
        profile=resolved_profile.name,
        profile_config={
            **resolved_profile.resolved(),
            "enabled_extensions": [item.resolved() for item in extension_details],
        },
    )
    result = generator.generate(request)
    bundle = AuditBundle.write(output or default_runs_root(), request, result)
    if output_format == "jsonl":
        for case in result.cases:
            record = asdict(case)
            record["schema_version"] = SCHEMA_VERSION
            record["input_hash"] = result.input_hash
            typer.echo(json.dumps(record, ensure_ascii=False, sort_keys=True))
    elif output_format == "text":
        for case in result.cases:
            escaped = case.text.encode("unicode_escape").decode("ascii")
            typer.echo(f"case-{case.id[:8]} [{','.join(case.techniques)}] {escaped}")
    else:
        raise typer.BadParameter("format must be text or jsonl")
    typer.echo(f"Audit bundle: {bundle.path}", err=True)


@app.command()
def techniques() -> None:
    """List built-in mutation techniques."""
    for name in PromptGenerator.techniques():
        typer.echo(name)
    for item in discover_extensions():
        typer.echo(f"{item.name}\tinstalled extension {item.package}=={item.version} (disabled)")


@app.command()
def profiles(
    output_format: Annotated[str, typer.Option("--format", help="text or json")] = "text",
) -> None:
    """List effective built-in and custom profiles."""
    try:
        items = available_profiles()
    except ValueError as exc:
        raise typer.ClickException(str(exc)) from exc
    if output_format == "json":
        typer.echo(json.dumps([item.resolved() for item in items], ensure_ascii=False, indent=2))
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text or json")
    table = Table(
        title="Available profiles",
        box=box.ROUNDED,
        header_style="bold",
        row_styles=("", "on grey3"),
        expand=True,
    )
    table.add_column("Profile", style="bold cyan", no_wrap=True, min_width=15)
    table.add_column("Cases", justify="right", no_wrap=True, width=5)
    table.add_column("Intensity", no_wrap=True, width=9)
    table.add_column("Chain length", justify="center", no_wrap=True, width=12)
    table.add_column("Techniques", ratio=1)
    for item in items:
        source = "built-in" if item.source.startswith("builtin:") else item.source
        profile_label = Text(item.name, style="bold cyan")
        profile_label.append(f"\n{source}", style="dim")
        table.add_row(
            profile_label,
            str(item.count),
            item.intensity,
            (
                str(item.min_chain_length)
                if item.min_chain_length == item.max_chain_length
                else f"{item.min_chain_length}–{item.max_chain_length}"
            ),
            ", ".join(item.techniques),
        )
    console = Console()
    console.print(table)
    console.print("[dim]Use with:[/dim] llm-redteam generate '…' --profile [bold]NAME[/bold]")


@app.command()
def verify(path: Annotated[Path, typer.Argument(exists=True, file_okay=False)]) -> None:
    """Verify all files in a finalized audit bundle."""
    result = AuditBundle.verify(path)
    if result.valid:
        typer.echo("valid")
        return
    for mismatch in result.mismatches:
        typer.echo(mismatch, err=True)
    raise typer.Exit(2)


@app.command()
def report(path: Annotated[Path, typer.Argument(exists=True, file_okay=False)]) -> None:
    """Rebuild a bundle's safe, self-contained HTML report."""
    report_path = AuditBundle.rebuild_report(path)
    typer.echo(str(report_path))


@runs_app.command("list")
def list_runs() -> None:
    root = default_runs_root()
    if not root.exists():
        return
    for path in sorted((item for item in root.iterdir() if item.is_dir()), reverse=True):
        typer.echo(path.name)


@runs_app.command("show")
def show_run(run_id: str) -> None:
    path = _resolved_run(run_id)
    run = json.loads((path / "run.json").read_text(encoding="utf-8"))
    typer.echo(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True))


@runs_app.command("delete")
def delete_run(
    run_id: str,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
) -> None:
    path = _resolved_run(run_id)
    if not yes:
        typer.confirm(f"Permanently delete {path}?", abort=True)
    shutil.rmtree(path)
    typer.echo(f"Deleted {path}")


def _resolved_run(run_id: str) -> Path:
    if Path(run_id).name != run_id or run_id in {"", ".", ".."}:
        raise typer.BadParameter("run ID must be a name, not a path")
    root = default_runs_root().resolve()
    path = (root / run_id).resolve()
    if path.parent != root or not path.is_dir():
        raise typer.BadParameter(f"unknown run ID: {run_id}")
    return path


if __name__ == "__main__":
    app()
