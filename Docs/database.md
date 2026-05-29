# Database Architecture — WISAXIS Resume Maker

> **Engine:** SQLite (development) · PostgreSQL-compatible (production) · ORM: SQLAlchemy 2.0

---

## 1. Design Philosophy

The database schema is designed around three principles:

1. **Frontend-aligned data shape** — `Resume.to_dict()` returns a dict that exactly mirrors the Vue wizard's `formData` object, so the backend can hydrate the form for editing without any transformation layer
2. **Ownership isolation** — every query for user-owned data includes `user_id=current_user.id` in the filter, making horizontal data isolation a database guarantee, not just an application concern
3. **Lightweight denormalization where it makes sense** — Skills (comma-separated text) and Languages (JSON array) are stored as single columns because the wizard treats them as single inputs. Normalizing them into separate tables would add complexity with zero query benefit at this scale.

---

## 2. Complete Table Definitions

### 2.1 `users`

```sql
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          VARCHAR(120)  NOT NULL,
    email         VARCHAR(254)  NOT NULL UNIQUE,
    password_hash VARCHAR(256)  NOT NULL,
    is_admin      BOOLEAN       NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME,
    last_login_at DATETIME
);
CREATE INDEX ix_users_email ON users (email);
```

**Notes:**
- `email` has a unique constraint enforced both at DB level and application level
- `password_hash` stores the output of `werkzeug.security.generate_password_hash` (PBKDF2-SHA256, never plaintext)
- `is_active=FALSE` soft-disables an account without deleting data (admin feature)
- `last_login_at` is updated on every successful login — useful for audit trails and inactive user cleanup

---

### 2.2 `user_settings`

```sql
CREATE TABLE user_settings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    default_template    VARCHAR(50)  DEFAULT 'template1',
    email_notifications BOOLEAN      DEFAULT TRUE,
    theme_preference    VARCHAR(20)  DEFAULT 'dark',
    updated_at          DATETIME
);
```

**Notes:**
- 1-to-1 relationship enforced by `UNIQUE` on `user_id`
- Created automatically with defaults at signup via `db.session.flush()` + `UserSettings(user_id=new_user.id)`
- `ON DELETE CASCADE` — deleting a user removes their settings

---

### 2.3 `resumes`

```sql
CREATE TABLE resumes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template    VARCHAR(50)  NOT NULL DEFAULT 'template1',
    name        VARCHAR(120) NOT NULL,
    title       VARCHAR(120) NOT NULL,
    email       VARCHAR(254) NOT NULL,
    phone       VARCHAR(30),
    address     VARCHAR(255),
    photo_url   VARCHAR(512),
    summary     TEXT,
    skills      TEXT,          -- "Python, Flask, SQL" (comma-separated)
    languages   TEXT,          -- '["English (Native)", "French (B2)"]' (JSON)
    version     INTEGER NOT NULL DEFAULT 1,
    is_deleted  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME
);
CREATE INDEX ix_resumes_user_id ON resumes (user_id);
```

**Denormalization rationale:**
- **`skills`** — stored as comma-separated string because the wizard input is `<input type="text" placeholder="Python, Flask, SQL">`. No query ever needs to filter by individual skill at this scale. The `skills_list` property on the model converts it to a list on demand.
- **`languages`** — stored as JSON array string because `json.loads()` is O(1) and the list is always loaded as a whole unit.

**Soft delete:** `is_deleted=TRUE` hides a resume from the user's profile without destroying the data. All queries add `filter_by(is_deleted=False)`. A cron job can hard-delete records older than 30 days.

---

### 2.4 `experiences`

```sql
CREATE TABLE experiences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id   INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    title       VARCHAR(150) NOT NULL,
    company     VARCHAR(150),
    duration    VARCHAR(100),   -- "Jan 2020 – Present"
    description TEXT
);
CREATE INDEX ix_experiences_resume_id ON experiences (resume_id);
```

**Update strategy:** On every resume save, all experience rows for that `resume_id` are deleted (`DELETE WHERE resume_id=X`) and re-inserted in order. This is simpler and more reliable than diffing individual rows, and at the scale of 1–5 experience entries per resume, the performance difference is negligible.

---

### 2.5 `educations`

```sql
CREATE TABLE educations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id   INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    degree      VARCHAR(200),   -- "B.Sc Computer Science"
    university  VARCHAR(200),
    year        VARCHAR(50)     -- "2021" or "2018–2022"
);
CREATE INDEX ix_educations_resume_id ON educations (resume_id);
```

---

### 2.6 `resume_versions`

```sql
CREATE TABLE resume_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id   INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL,
    snapshot    TEXT    NOT NULL,   -- JSON blob of Resume.to_dict()
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_resume_versions_resume_id ON resume_versions (resume_id);
```

**Version control strategy:**
1. Before any update, `_snapshot_resume(resume)` is called
2. It creates a `ResumeVersion` row with the current `resume.version` number and a full JSON snapshot
3. `resume.version` is then incremented
4. On rollback (future feature), deserialize the snapshot and re-apply it

The API returns up to 20 versions ordered by `version_num DESC`.

---

### 2.7 `export_history`

```sql
CREATE TABLE export_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id   INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    format      VARCHAR(10) DEFAULT 'pdf',   -- 'pdf' | 'json' | 'doc'
    exported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_export_history_resume_id ON export_history (resume_id);
```

**Use cases:**
- Analytics: "How many resumes were downloaded last month?"
- Per-user: "How many times has this resume been exported?"
- Format breakdown: PDF vs JSON preference

---

### 2.8 `ai_history`

```sql
CREATE TABLE ai_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resume_id     INTEGER REFERENCES resumes(id) ON DELETE SET NULL,
    action        VARCHAR(60) NOT NULL,   -- 'generate_summary', 'chat', 'ats_score', ...
    prompt        TEXT,                  -- truncated to 2000 chars
    response      TEXT,                  -- truncated to 4000 chars
    model_used    VARCHAR(100),
    tokens_used   INTEGER DEFAULT 0,
    success       BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_ai_history_user_id ON ai_history (user_id);
```

**Design decisions:**
- `resume_id` is nullable (`ON DELETE SET NULL`) — AI history is preserved even if the resume is deleted
- `prompt` and `response` are truncated at storage time (2000/4000 chars) to prevent unbounded growth
- `tokens_used` enables per-user token budgeting (future: add a monthly cap)
- `error_message` captures API error details when `success=FALSE`

---

### 2.9 `templates`

```sql
CREATE TABLE templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        VARCHAR(50) NOT NULL UNIQUE,   -- 'template1'
    name        VARCHAR(80) NOT NULL,           -- 'Executive'
    tag         VARCHAR(50),                    -- 'Professional'
    preview_img VARCHAR(120),                   -- 'templateA.webp'
    is_active   BOOLEAN DEFAULT TRUE,
    sort_order  INTEGER DEFAULT 0
);
```

**Seed data:** 8 rows are inserted on first startup by `seed_templates()`. This function is idempotent — it checks for existing slugs before inserting, so calling it multiple times is safe.

---

## 3. Entity-Relationship Diagram

```
users ──────────────────────────────────────────────┐
  │ 1                                                │ 1
  │ ∞                                                │ 1
  ├── resumes                                        └── user_settings
  │     │ 1
  │     ├── experiences (∞)
  │     ├── educations  (∞)
  │     ├── resume_versions (∞)
  │     └── export_history (∞)
  │
  └── ai_history (∞)
          │ (nullable FK)
          └── resumes
```

**Cardinalities:**
| Relationship | Type | On Delete |
|---|---|---|
| User → Resumes | 1-to-many | CASCADE |
| User → UserSettings | 1-to-1 | CASCADE |
| User → AIHistory | 1-to-many | CASCADE |
| Resume → Experiences | 1-to-many | CASCADE |
| Resume → Educations | 1-to-many | CASCADE |
| Resume → ResumeVersions | 1-to-many | CASCADE |
| Resume → ExportHistory | 1-to-many | CASCADE |
| Resume → AIHistory | 1-to-many | SET NULL |

---

## 4. Normalization Analysis

| Level | Status | Notes |
|---|---|---|
| 1NF | ✅ | All columns hold atomic values; skills/languages are intentional denormalizations |
| 2NF | ✅ | No partial dependencies; all non-key columns depend on the full primary key |
| 3NF | ✅ | No transitive dependencies between non-key columns |
| BCNF | ✅ | No non-trivial functional dependencies on non-superkeys |

---

## 5. Indexing Strategy

| Table | Index Columns | Query Pattern |
|---|---|---|
| `users` | `email` | Login lookup: `WHERE email = ?` |
| `resumes` | `user_id` | Profile page: `WHERE user_id = ? AND is_deleted = FALSE` |
| `resumes` | `(user_id, is_deleted, updated_at)` | *(Recommended)* Profile + sort |
| `experiences` | `resume_id` | Eager loading with resume |
| `educations` | `resume_id` | Eager loading with resume |
| `resume_versions` | `resume_id` | Version history list |
| `export_history` | `resume_id` | Export count query |
| `ai_history` | `user_id` | Per-user AI history |

---

## 6. SQLAlchemy ORM Configuration

```python
SQLALCHEMY_DATABASE_URI = "sqlite:///instance/wisaxis.db"
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,   # Test connections before use
    "pool_recycle": 300,     # Recycle stale connections every 5 min
}
```

**Eager loading:** Experience and Education rows use `lazy="selectin"` — when a `Resume` is loaded, SQLAlchemy issues a single `SELECT ... WHERE resume_id IN (...)` to load all child rows, instead of N+1 queries.

---

## 7. Query Optimization Patterns

### Profile page query
```python
Resume.query
    .filter_by(user_id=current_user.id, is_deleted=False)
    .order_by(Resume.updated_at.desc())
    .all()
```
Add a composite index: `CREATE INDEX ix_resumes_user_active_date ON resumes(user_id, is_deleted, updated_at DESC)`

### Paginated resume API
```python
Resume.query
    .filter_by(user_id=current_user.id, is_deleted=False)
    .order_by(Resume.updated_at.desc())
    .paginate(page=page, per_page=12, error_out=False)
```

### AI history cleanup (recommended cron)
```sql
DELETE FROM ai_history
WHERE created_at < datetime('now', '-90 days');
```

---

## 8. Migration Strategy (SQLite → PostgreSQL)

When you outgrow SQLite (typically at >10K users or high write concurrency):

1. **Change `DATABASE_URL`** in `.env` to a PostgreSQL connection string — SQLAlchemy's dialect abstraction handles the rest
2. **Generate a schema dump** from SQLite: `sqlite3 wisaxis.db .dump > schema.sql`
3. **Apply with Alembic** for future schema changes:
   ```bash
   flask db init
   flask db migrate -m "initial"
   flask db upgrade
   ```
4. **Data migration** using `pg_restore` or a custom script

**Incompatibilities to watch:**
- SQLite's `BOOLEAN` stores as 0/1 integers — PostgreSQL uses native `BOOLEAN`
- `AUTOINCREMENT` → `SERIAL` / `BIGSERIAL` in PostgreSQL
- `DATETIME` → `TIMESTAMP WITH TIME ZONE` in PostgreSQL

---

## 9. Scalability Planning

| Milestone | Users | Action Required |
|---|---|---|
| Current | 0–10K | SQLite (default) |
| Phase 2 | 10K–100K | PostgreSQL + connection pooling (PgBouncer) |
| Phase 3 | 100K+ | Read replicas + query caching (Redis) |
| Phase 4 | 1M+ | Horizontal sharding or switch to a managed DB (PlanetScale / Neon) |
