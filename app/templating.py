"""Shared Jinja2 template environment for route handlers."""

from pathlib import Path
from urllib.parse import quote

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

_templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def invite_register_url(request: Request, code: str) -> str:
    """Absolute signup URL for an invitation code."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/register?code={quote(code, safe='')}"


templates.env.globals["invite_register_url"] = invite_register_url
