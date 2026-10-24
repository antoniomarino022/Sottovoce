from fastapi.templating import Jinja2Templates
from config.settings import settings

templates = Jinja2Templates(directory="src/templates")

# Optimize template cache: disable auto_reload in production
if getattr(settings, "ENVIRONMENT", "development") == "production":
    templates.env.auto_reload = False
    templates.env.cache_size = 400
