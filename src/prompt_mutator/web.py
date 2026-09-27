"""Local-only web interface for LLM Red Team Workbench."""

from __future__ import annotations

import threading
import unicodedata
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .audit import AuditBundle
from .catalog import PROFILE_DESCRIPTIONS, TECHNIQUE_DESCRIPTIONS, display_name
from .generator import PromptGenerator
from .models import GeneratedCase, GenerationRequest
from .profiles import available_profiles, load_profile


ASSET_ROOT = Path(__file__).with_name("web_assets")
ALLOWED_COUNTS = {25, 50, 100, 250, 500, 1000}
ASSET_TYPES = {
    "styles.css": "text/css",
    "app.js": "text/javascript",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply a locked-down policy suitable for adversarial prompt content."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; img-src 'self' data:; object-src 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response


def create_app(
    *,
    runs_root: Path | None = None,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver"),
) -> Starlette:
    """Create the local web application without starting a server."""
    if runs_root is None:
        from .cli import default_runs_root

        runs_root = default_runs_root()
    app = Starlette(
        debug=False,
        routes=[
            Route("/", _index),
            Route("/api/health", _health),
            Route("/api/catalog", _catalog),
            Route("/api/generate", _generate, methods=["POST"]),
            Route("/assets/{name:str}", _asset),
        ],
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts)),
            Middleware(SecurityHeadersMiddleware),
        ],
        exception_handlers={HTTPException: _http_error},
    )
    app.state.runs_root = Path(runs_root)
    return app


async def _index(request: Request) -> Response:
    return Response(
        (ASSET_ROOT / "index.html").read_bytes(),
        media_type="text/html",
    )


async def _asset(request: Request) -> Response:
    name = request.path_params["name"]
    media_type = ASSET_TYPES.get(name)
    if media_type is None:
        raise HTTPException(404, "Asset not found")
    return Response((ASSET_ROOT / name).read_bytes(), media_type=media_type)


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)


async def _catalog(request: Request) -> JSONResponse:
    profiles = []
    for profile in available_profiles():
        resolved = profile.resolved()
        resolved["label"] = display_name(profile.name)
        resolved["description"] = PROFILE_DESCRIPTIONS.get(
            profile.name,
            f"Configured profile using {len(profile.techniques)} techniques.",
        )
        resolved["source_label"] = (
            "Built in" if profile.source.startswith("builtin:") else profile.source
        )
        profiles.append(resolved)
    techniques = [
        {
            "name": name,
            "label": display_name(name),
            "description": TECHNIQUE_DESCRIPTIONS[name],
        }
        for name in PromptGenerator.techniques()
    ]
    return JSONResponse({"profiles": profiles, "techniques": techniques})


async def _generate(request: Request) -> JSONResponse:
    _validate_origin(request)
    if request.headers.get("content-length"):
        try:
            if int(request.headers["content-length"]) > 150_000:
                raise HTTPException(413, "Request exceeds the 150 KB limit")
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length header") from None
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Request body must be valid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "Request body must be a JSON object")
    generation_request = _build_generation_request(payload)

    def generate_and_write() -> tuple[Any, AuditBundle]:
        result = PromptGenerator().generate(generation_request)
        bundle = AuditBundle.write(request.app.state.runs_root, generation_request, result)
        return result, bundle

    result, bundle = generate_and_write()
    return JSONResponse(
        {
            "run_id": bundle.path.name,
            "audit_path": str(bundle.path),
            "summary": {
                "cases": len(result.cases),
                "attempted": result.attempted,
                "skipped": len(result.skipped),
                "errors": len(result.errors),
            },
            "cases": [_case_payload(case) for case in result.cases],
        }
    )


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlparse(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.netloc != request.headers.get("host")
    ):
        raise HTTPException(403, "Cross-origin requests are not allowed")


def _build_generation_request(payload: dict[str, Any]) -> GenerationRequest:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise HTTPException(422, "Enter a prompt before generating cases")
    if len(prompt.encode("utf-8")) > 100_000:
        raise HTTPException(413, "Prompt exceeds the 100 KB limit")

    profile_name = payload.get("profile", "baseline")
    intensity = payload.get("intensity", "medium")
    count = payload.get("count", 25)
    if not isinstance(profile_name, str):
        raise HTTPException(422, "Profile must be a string")
    if intensity not in {"low", "medium", "high", "max"}:
        raise HTTPException(422, "Intensity must be low, medium, high, or max")
    if not isinstance(count, int) or isinstance(count, bool) or count not in ALLOWED_COUNTS:
        raise HTTPException(422, "Case count must be one of 25, 50, 100, 250, 500, or 1000")

    known = set(PromptGenerator.techniques())
    pipelines: tuple[tuple[str, ...], ...] = ()
    if profile_name == "custom":
        selected = _technique_list(payload.get("techniques"), known, "custom techniques")
        if not selected:
            raise HTTPException(422, "Select at least one custom technique")
        techniques = selected
        min_chain_length = max_chain_length = 1
        profile_config = _session_profile(
            profile_name, techniques, count, intensity, 1, 1
        )
    elif profile_name == "custom_chain":
        chain = _technique_list(payload.get("chain"), known, "custom chain")
        if len(chain) not in {2, 3}:
            raise HTTPException(422, "Custom chain requires exactly two or three steps")
        techniques = chain
        pipelines = (chain,)
        min_chain_length = max_chain_length = len(chain)
        profile_config = _session_profile(
            profile_name,
            techniques,
            count,
            intensity,
            len(chain),
            len(chain),
            pipelines=[list(chain)],
        )
    else:
        try:
            profile = load_profile(profile_name)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        techniques = profile.techniques
        min_chain_length = profile.min_chain_length
        max_chain_length = profile.max_chain_length
        profile_config = {
            **profile.resolved(),
            "count": count,
            "intensity": intensity,
        }

    projected_bytes = count * (len(prompt.encode("utf-8")) * 10 + 800)
    if projected_bytes > 250 * 1024 * 1024:
        raise HTTPException(413, "Projected audit bundle exceeds the 250 MB limit")
    return GenerationRequest(
        prompt=prompt,
        techniques=techniques,
        pipelines=pipelines,
        count=count,
        seed=0,
        intensity=intensity,
        min_chain_length=min_chain_length,
        max_chain_length=max_chain_length,
        profile=profile_name,
        profile_config=profile_config,
    )


def _technique_list(value: Any, known: set[str], label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HTTPException(422, f"{label.title()} must be a list of technique names")
    unknown = set(value) - known
    if unknown:
        raise HTTPException(422, "Unknown technique(s): " + ", ".join(sorted(unknown)))
    return tuple(value)


def _session_profile(
    name: str,
    techniques: tuple[str, ...],
    count: int,
    intensity: str,
    minimum: int,
    maximum: int,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "version": 1,
        "techniques": list(techniques),
        "count": count,
        "intensity": intensity,
        "min_chain_length": minimum,
        "max_chain_length": maximum,
        "source": "web-session",
        **extra,
    }


def _case_payload(case: GeneratedCase) -> dict[str, Any]:
    noteworthy = []
    seen: set[str] = set()
    for character in case.text:
        category = unicodedata.category(character)
        if character in seen or not (
            ord(character) > 127 or category.startswith("C") or unicodedata.combining(character)
        ):
            continue
        seen.add(character)
        noteworthy.append(
            {
                "value": f"U+{ord(character):04X}",
                "name": unicodedata.name(character, "UNNAMED"),
                "category": category,
            }
        )
    return {
        "id": case.id,
        "short_id": f"case-{case.id[:8]}",
        "text": case.text,
        "escaped": case.text.encode("unicode_escape").decode("ascii"),
        "encoded": "".join(
            f"\\u{ord(character):04x}"
            if ord(character) <= 0xFFFF
            else f"\\U{ord(character):08x}"
            for character in case.text
        ),
        "techniques": list(case.techniques),
        "technique_label": " → ".join(case.techniques),
        "parameters": case.parameters,
        "changed_positions": list(case.changed_positions),
        "code_points": noteworthy,
    }


def run_web(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    allowed_hosts: tuple[str, ...] = (),
    open_browser: bool = True,
) -> None:
    """Run the web UI, requiring an explicit host allowlist for remote binds."""
    import uvicorn

    remote = host not in {"127.0.0.1", "localhost", "::1"}
    if remote and not allowed_hosts:
        raise ValueError("remote binding requires at least one --allowed-host value")
    trusted = tuple(dict.fromkeys(("127.0.0.1", "localhost", *allowed_hosts)))
    browser_host = allowed_hosts[0] if host == "0.0.0.0" else host
    url = f"http://{browser_host}:{port}"
    if open_browser:
        timer = threading.Timer(0.7, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()
    uvicorn.run(
        create_app(allowed_hosts=trusted),
        host=host,
        port=port,
        log_level="warning",
    )
