# Deployment Architecture — WISAXIS Resume Maker

> Comprehensive guide for deploying the WISAXIS Resume Maker to both development and production environments.

---

## 1. Local Development Setup

### 1.1 Prerequisites
- Python 3.12 or higher
- Git

### 1.2 Installation Steps

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd resume2.0
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   - Copy the example config: `cp .env.example .env` (or `copy .env.example .env` on Windows)
   - Open `.env` and add your `OPENROUTER_API_KEY`. Get a free key at [openrouter.ai](https://openrouter.ai).
   - Ensure `FLASK_ENV=development` is set.

5. **Run the development server:**
   ```bash
   python app.py
   ```
   The application will be available at `http://127.0.0.1:5050`. The SQLite database (`instance/wisaxis.db`) will be created automatically on the first request.

---

## 2. Production Deployment

For a production environment, you should never use the built-in Flask development server. A WSGI server like Gunicorn is required.

### 2.1 Environment Configuration (`.env`)

In production, these variables MUST be set securely in your hosting provider's dashboard, not committed to code:

```env
FLASK_ENV=production
FLASK_DEBUG=false
SECRET_KEY=generate_a_secure_64_character_random_string_here
OPENROUTER_API_KEY=your_production_openrouter_key
```

**Optional but recommended for production:**
- `DATABASE_URL`: Set to a PostgreSQL connection string instead of relying on the default SQLite database.
- `REDIS_URL`: Set to a Redis connection string to enable shared, persistent rate-limiting across multiple worker processes.

### 2.2 Running with Gunicorn

Start the application using Gunicorn:

```bash
gunicorn "backend:create_app()" --bind 0.0.0.0:8000 --workers 4
```

*Rule of thumb for workers:* `(2 x $num_cores) + 1`

---

## 3. Deployment Platforms

### 3.1 Render.com (Recommended for ease of use)

1. Connect your GitHub repository to Render.
2. Create a new **Web Service**.
3. **Environment:** Python 3
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:** `gunicorn "backend:create_app()" --bind 0.0.0.0:$PORT --workers 2`
6. Add Environment Variables in the Render dashboard:
   - `PYTHON_VERSION`: 3.12.x
   - `SECRET_KEY`: (generate a random string)
   - `OPENROUTER_API_KEY`: (your key)
7. Render provisions a PostgreSQL database easily if you wish to upgrade from SQLite.

### 3.2 Railway.app

1. Deploy from GitHub repository.
2. Railway automatically detects the Python environment and `requirements.txt`.
3. Set the custom Start Command in settings: `gunicorn "backend:create_app()" --bind 0.0.0.0:$PORT`
4. Add your Environment Variables.
5. Railway allows easy provisioning of PostgreSQL and Redis services within the same project.

---

## 4. Scaling Strategy

As the application grows, the current architecture supports scaling through these phases:

### Phase 1: Vertical Scaling (Current)
- **Database:** SQLite (file-based). Suitable for up to ~10k users.
- **Compute:** Increase server RAM/CPU and add more Gunicorn workers.
- **Limitation:** SQLite locks the entire database on writes. Concurrent writes will eventually bottleneck.

### Phase 2: Horizontal Scaling
To run the application across multiple servers (horizontal scaling), you must eliminate local state:
1. **Database:** Migrate from SQLite to a managed PostgreSQL instance (e.g., AWS RDS, Supabase).
2. **File Uploads:** Move user profile photos (`instance/uploads`) from local disk to object storage (e.g., AWS S3, Cloudflare R2). Update the upload route in `routes/api.py` to upload directly to S3 and store the S3 URL in the database.
3. **Rate Limiting:** Provide a `REDIS_URL` in the environment so Flask-Limiter tracks request counts centrally rather than in the local memory of each worker process.

### Phase 3: Performance Optimization
- **Database Connection Pooling:** Implement PgBouncer or configure SQLAlchemy engine options (`pool_size`, `max_overflow`).
- **CDN:** Serve all static assets (`frontend/static/css`, `frontend/static/js`, `frontend/static/images`) through a CDN like Cloudflare to reduce server load.
- **Async AI Generation:** Currently, AI calls block the HTTP request thread. For high concurrency, offload `AIService` calls to a Celery task queue (backed by Redis or RabbitMQ). The frontend would poll for task completion or use WebSockets.

---

## 5. CI/CD Pipeline Suggestions

Implement a basic GitHub Actions workflow (`.github/workflows/main.yml`) to enforce code quality before deployment:

1. **Linting & Formatting:** Use `ruff` or `flake8` to enforce Python styling.
2. **Type Checking:** Run `mypy` to catch type errors.
3. **Testing:** Run a `pytest` suite. Set `FLASK_ENV=testing` to use the in-memory database and skip external API calls by mocking `AIService`.
4. **Deployment Trigger:** If tests pass on the `main` branch, trigger a deployment webhook to your hosting provider (Render/Railway).
