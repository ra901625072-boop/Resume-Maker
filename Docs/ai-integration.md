# AI Integration Architecture — WISAXIS Resume Maker

> **Provider:** OpenRouter API · **Protocol:** OpenAI-compatible REST · **Module:** `backend/services/ai_service.py`

---

## 1. Why OpenRouter?

OpenRouter is a unified API gateway that provides access to 100+ AI models (GPT-4o, Claude, Llama, Gemini, Mistral, etc.) through a single OpenAI-compatible endpoint. Key advantages for this project:

| Advantage | Detail |
|---|---|
| **Free tier** | `meta-llama/llama-3.1-8b-instruct:free` — zero cost for development |
| **Model flexibility** | Switch models by changing one `.env` variable — no code changes |
| **OpenAI-compatible** | Standard `POST /v1/chat/completions` format |
| **Fallback routing** | OpenRouter can automatically fall back to other models if one is unavailable |
| **Transparent pricing** | Per-token pricing shown on the dashboard |

---

## 2. AI Module Architecture

```
backend/services/ai_service.py
│
├── AIService (static class — no instantiation needed)
│   │
│   ├── Public Methods (called by route handlers)
│   │   ├── generate_summary(name, title, skills, experience_titles)
│   │   ├── generate_experience(title, company, duration, skills)
│   │   ├── chat(message, history)
│   │   ├── ats_score(resume_dict)
│   │   ├── generate_cover_letter(name, title, company, job_desc, skills)
│   │   ├── improve_grammar(text)
│   │   ├── suggest_skills(job_title, existing_skills)
│   │   └── extract_resume_from_file(file_path, ext)
│   │
│   └── Private Methods
│       ├── _call(prompt, action, max_tokens)
│       ├── _call_with_messages(messages, action, max_tokens)
│       └── (helpers) _log_ai_history, _dict_to_text, _extract_text_from_file
```

**Design:** All route handlers delegate to `AIService` methods. The service reads configuration from Flask's `current_app.config` — this means it always uses the current app's API key and model without needing them passed as arguments.

---

## 3. API Request Architecture

### 3.1 HTTP Request Structure

```python
headers = {
    "Authorization":  f"Bearer {api_key}",
    "Content-Type":   "application/json",
    "HTTP-Referer":   "https://wisaxis.com",    # For OpenRouter billing attribution
    "X-Title":        "WISAXIS Resume Maker",    # Shown in OpenRouter dashboard
}

payload = {
    "model":       "meta-llama/llama-3.1-8b-instruct:free",
    "messages":    [{"role": "user", "content": "..."}],
    "max_tokens":  1024,
    "temperature": 0.7,
}

response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    json=payload,
    timeout=30,
)
```

### 3.2 Response Parsing

```python
content     = response.json()["choices"][0]["message"]["content"].strip()
tokens_used = response.json().get("usage", {}).get("total_tokens", 0)
```

---

## 4. Prompt Engineering Strategy

### 4.1 Professional Summary Prompt

**Design philosophy:** Explicit constraints prevent the AI from producing generic, clichéd output (e.g., "results-driven team player").

```python
prompt = f"""
Write a professional resume summary for {name}, a {title} with experience as {exp_context}.
Key skills: {skills}.

Requirements:
- 3-5 sentences, first-person style
- ATS-friendly with strong action verbs
- Highlight value, not just responsibilities
- Do not include a heading or label
- Do not use clichés like 'results-driven' or 'team player'
"""
```

**Temperature:** `0.7` — high enough for varied, natural language; low enough to stay professional.

### 4.2 Experience Bullet Points (CAR Framework)

The **CAR framework** (Challenge → Action → Result) is explicitly requested:

```python
prompt = f"""
Job Title: {title}
Company: {company}
Duration: {duration}
Skills used: {skills}

Write 3-5 impactful resume bullet points for this work experience.
Requirements:
- Use the CAR framework (Challenge → Action → Result)
- Start each bullet with a strong past-tense action verb
- Include quantifiable results where possible (percentages, numbers)
- ATS-optimised keywords for the job title
- Output only bullet points, no headings
- Format each bullet on a new line starting with •
"""
```

### 4.3 Multi-Turn Chat System Prompt

The chat uses a **system message** to maintain consistent persona across all turns:

```python
{
    "role": "system",
    "content": (
        "You are WISAXIS AI, an expert resume writer and career coach. "
        "You specialise in ATS optimisation, impactful wording, and professional formatting. "
        "Be concise, professional, and always practical. "
        "When writing resume content, use strong action verbs and quantifiable achievements. "
        "Format using markdown."
    )
}
```

### 4.4 ATS Score — Structured JSON Output

The ATS scorer requests a **structured JSON response** to enable frontend processing:

```python
prompt = f"""
Analyse the following resume and give an ATS compatibility score from 0 to 100.

Resume:
{resume_text}

Return a JSON object with exactly these keys:
  "score": integer 0-100
  "summary": one sentence overall assessment
  "strengths": array of 2-3 strong points
  "improvements": array of 3-5 specific improvements

Return ONLY the JSON, no extra text.
"""
```

The response is then parsed with `json.loads()`. If parsing fails (the model returns extra text), the raw string is returned as-is.

---

## 5. Context Window Management

### Chat History Truncation

To prevent exceeding the model's context window, only the **last 10 turns** of chat history are sent:

```python
for turn in history[-10:]:   # Most recent 10 turns
    if turn.get("role") in ("user", "assistant") and turn.get("content"):
        messages.append({"role": turn["role"], "content": turn["content"]})
```

At ~200 tokens per turn average, 10 turns = ~2,000 tokens of history, leaving plenty of room for the system prompt, current message, and response within an 8K context window.

### Token Budget by Action

| Action | `max_tokens` | Rationale |
|---|---|---|
| `generate_summary` | 1024 (default) | 3-5 sentences — needs ~300 tokens |
| `generate_experience` | 1024 (default) | 3-5 bullets — needs ~400 tokens |
| `chat` | 2048 | Longer conversational responses |
| `ats_score` | 512 | Structured JSON output is compact |
| `cover_letter` | 1024 | ~400 words |
| `improve_grammar` | 1024 | Same length as input |
| `suggest_skills` | 256 | Short comma-separated list |
| `extract_resume` | 2048 | Full resume JSON extraction |

---

## 6. Error Handling & Fallback Strategy

### Error Classification

```python
except requests.exceptions.Timeout:
    # User-facing: "AI request timed out. Please try again."
    # Cause: Network latency or model overload

except requests.exceptions.HTTPError as e:
    if e.response.status_code == 401:
        "Invalid OpenRouter API key."
    elif e.response.status_code == 402:
        "OpenRouter credit balance is too low."
    elif e.response.status_code == 429:
        "AI rate limit reached. Please wait a moment."
    else:
        f"AI API error: {status_code}"

except Exception:
    "An unexpected error occurred with the AI service."
```

### Frontend Fallback

When an AI endpoint returns `{ success: false }`, the frontend shows a toast and **does not clear** the existing form data. The user can retry without losing their work.

---

## 7. AI History Logging

Every AI call — success or failure — is logged to the `ai_history` table:

```python
record = AIHistory(
    user_id       = current_user.id,
    action        = action,             # 'generate_summary', 'chat', etc.
    prompt        = prompt[:2000],      # Truncated to prevent DB bloat
    response      = content[:4000],     # Truncated
    model_used    = model,              # 'meta-llama/llama-3.1-8b-instruct:free'
    tokens_used   = tokens_used,
    success       = True,
    error_message = None,
)
```

**Benefits:**
1. Debug production issues by inspecting prompts/responses
2. Track per-user token consumption
3. Analytics: which features are used most?
4. A/B test different prompts by comparing outputs

---

## 8. AI Resume Data Extraction (JSON Parser)

When a user uploads a PDF/DOCX on the JSON features page:

```
1. File saved to /uploads/tmp_<uuid>.<ext>
2. Text extraction:
   - PDF:  pdfplumber → extract_text() per page → join with \n
   - DOCX: python-docx → paragraph.text → join with \n
3. Text (first 4000 chars) sent to AI with structured extraction prompt
4. AI returns JSON matching WISAXIS resume schema
5. json.loads() parses the response
6. Stored in Flask session as session['import_data']
7. User redirected to /dashboard
8. Temporary file deleted (finally block)
```

**Optional dependencies:** `pdfplumber` and `python-docx` are not in `requirements.txt` by default — they are listed as commented-out optional deps. Install them if you need PDF/DOCX extraction.

---

## 9. Token Optimization Strategy

| Technique | Implementation |
|---|---|
| **Prompt brevity** | Prompts are ~50-100 words; no verbose preamble |
| **Response constraints** | `max_tokens` set per action type (not a blanket 2048) |
| **History truncation** | Last 10 turns only in chat |
| **Text truncation** | Resume text capped at 4000 chars for ATS analysis |
| **Skip empty fields** | Empty experience/skills not included in prompts |

**Future optimization — Response caching:**
```python
import hashlib, json
from functools import lru_cache

def _cache_key(action: str, **kwargs) -> str:
    return hashlib.sha256(
        json.dumps({"action": action, **kwargs}, sort_keys=True).encode()
    ).hexdigest()

# Cache identical prompts in Redis with TTL=3600 (1 hour)
```
This would reduce API costs by ~30-40% since many users ask for similar summaries for the same job title.

---

## 10. Multi-Model Support

The model is configured via a single `.env` variable:

```env
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
```

**Available free alternatives on OpenRouter:**
| Model | Best For |
|---|---|
| `meta-llama/llama-3.1-8b-instruct:free` | Default — fast, capable |
| `mistralai/mistral-7b-instruct:free` | Good instruction following |
| `google/gemma-3-4b-it:free` | Compact, fast |

**Premium models (paid):**
| Model | Best For |
|---|---|
| `openai/gpt-4o-mini` | Cost-effective premium |
| `anthropic/claude-3.5-haiku` | Excellent at professional writing |
| `openai/gpt-4o` | Best quality, highest cost |

**Future enhancement:** Allow users to select their preferred model from the UI (store in `user_settings.preferred_ai_model`).

---

## 11. AI Feature Roadmap

| Feature | Status | Implementation |
|---|---|---|
| Summary generation | ✅ Done | `AIService.generate_summary()` |
| Experience bullets | ✅ Done | `AIService.generate_experience()` |
| AI chat assistant | ✅ Done | `AIService.chat()` |
| ATS scoring | ✅ Done | `AIService.ats_score()` |
| Cover letter | ✅ Done | `AIService.generate_cover_letter()` |
| Grammar improvement | ✅ Done | `AIService.improve_grammar()` |
| Skill suggestions | ✅ Done | `AIService.suggest_skills()` |
| File extraction | ✅ Done | `AIService.extract_resume_from_file()` |
| Response caching | 🔲 Planned | Redis + hash-based cache key |
| Async generation | 🔲 Planned | Celery task queue |
| Job description matching | 🔲 Planned | Compare resume vs JD, give gap analysis |
| LinkedIn import | 🔲 Planned | Parse LinkedIn profile JSON export |
| Interview prep | 🔲 Planned | Generate likely interview questions from resume |
