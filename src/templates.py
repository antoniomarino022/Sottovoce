from pathlib import Path

from fastapi.templating import Jinja2Templates
from config.settings import settings

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Disable filesystem stat checks on every render in serverless / production
if settings.is_serverless or getattr(settings, "ENVIRONMENT", "development") == "production":
    templates.env.auto_reload = False
    templates.env.cache_size = 400
