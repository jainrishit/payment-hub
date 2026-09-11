# Vercel entry point — re-exports the FastAPI app from app/main.py.
# Vercel's @vercel/python runtime looks for a module-level variable named `app`.
from app.main import app  # noqa: F401
