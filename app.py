"""
app.py — Application Entry Point
==================================
Run this file to start the development server.

Usage:
    python app.py

Production:
    gunicorn "backend:create_app()" --bind 0.0.0.0:$PORT --workers 2
"""

import os

# Load .env BEFORE importing anything that reads os.environ (config.py).
# python-dotenv only auto-loads when using `flask run`; for `python app.py`
# we must call this explicitly.
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)  # always apply .env so updates take effect on restart
except ImportError:
    pass  # python-dotenv not installed — rely on real environment variables

from backend import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    print(f"\nWISAXIS Resume Maker running at http://127.0.0.1:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
