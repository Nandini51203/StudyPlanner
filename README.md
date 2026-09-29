# Multi-Agent AI Study Assistant

Flask + LangChain (Gemini) + LangGraph + SQLite + Bootstrap/Chart.js. Runs in **DEMO mode** (sample data, clearly labelled) if no API key is set.

## Features

- **User Authentication** — Register, login, logout with password hashing (Werkzeug)
- **Study Materials** — Upload PDF/TXT files or type topics directly
- **AI Summarizer** — Generates structured summaries from your notes
- **Quiz Generator** — Creates MCQ quizzes (5/10/15 questions) with validation
- **Weak Topic Tracker** — Tracks topic-wise performance across attempts
- **Progress Dashboard** — Charts and analytics for scores and topic mastery
- **Multi-user** — Each user has their own materials, quizzes, and progress

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Flask 3.x (Python) |
| AI/LLM | Google Gemini via `langchain-google-genai` |
| Agent Orchestration | LangGraph (`StateGraph`) |
| Database | SQLite (via `sqlite3` stdlib) |
| Auth | Werkzeug password hashing + Flask sessions |
| Frontend | Jinja2 templates + Bootstrap 5.3 + Chart.js |
| PDF Processing | `pypdf` |

## Project Structure

```
multi_agent_study_assistant/
├── app.py                  # Main Flask application (entry point)
├── config.py               # Configuration (env vars, paths, settings)
├── auth.py                 # Authentication helpers (register, verify, login_required)
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── .env                    # Environment variables (gitignored)
├── .env.example            # Example env file
├── .gitignore              # Git ignore rules
├── sample_notes.txt        # Sample study notes for testing
│
├── agents/                 # AI agent modules
│   ├── __init__.py
│   ├── llm.py              # LLM helper (Gemini via LangChain)
│   ├── summarizer_agent.py # Notes -> structured summary
│   ├── quiz_agent.py       # Generates MCQ quizzes
│   ├── weak_topic_agent.py # Tracks topic performance
│   └── study_graph.py      # LangGraph orchestration
│
├── database/               # Database layer
│   ├── __init__.py
│   └── db.py               # SQLite connection, schema, queries
│
├── services/               # Service layer
│   ├── __init__.py
│   └── pdf_service.py      # PDF/TXT text extraction
│
├── static/                 # Frontend static assets
│   ├── css/
│   │   └── style.css       # Custom styles
│   └── js/
│       ├── main.js         # Main JS (API calls, navigation)
│       └── charts.js       # Chart.js wrappers
│
├── templates/              # Jinja2 HTML templates
│   ├── base.html           # Base layout (sidebar nav, Bootstrap)
│   ├── login.html          # Login page
│   ├── register.html       # Registration page
│   ├── dashboard.html      # Home dashboard
│   ├── materials.html      # Upload/manage study materials
│   ├── summary.html        # View generated summary
│   ├── quiz.html           # Take a quiz (JS-driven)
│   ├── results.html        # Quiz results + feedback
│   └── progress.html       # Progress charts & topic tracking
│
├── instance/
│   └── study.db            # SQLite database file (auto-created)
│
└── uploads/                # Uploaded files (if saved to disk)
```

## Database Schema

The SQLite database (`instance/study.db`) contains the following tables:

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | Registered users | `id`, `username`, `password_hash`, `email`, `created` |
| `materials` | Uploaded study materials | `id`, `user_id`, `name`, `content`, `created` |
| `summaries` | AI-generated summaries per material | `material_id` (PK), `data` (JSON), `demo` flag |
| `quizzes` | Generated quizzes per material | `id`, `material_id`, `questions` (JSON), `demo` flag |
| `attempts` | Quiz attempts (scores) | `id`, `quiz_id`, `material_id`, `score`, `total`, `feedback` (JSON) |
| `answers` | Individual answer records | `id`, `attempt_id`, `topic`, `selected`, `correct`, `is_correct` |

**View:** `topic_performance` — aggregates answers by material and topic.

## How to Run (Step by Step)

### Prerequisites

- **Python 3.10+** installed
- **pip** (Python package manager)
- A **Google Gemini API key** (free) — [Get one here](https://aistudio.google.com/app/apikey)

### Windows (PowerShell)

```powershell
# 1. Navigate to the project folder
cd multi_agent_study_assistant

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the virtual environment
.\venv\Scripts\Activate.ps1
# If you get an execution policy error, run this first:
# Set-ExecutionPolicy -Scope Process Bypass

# 4. Install dependencies
pip install -r requirements.txt

# 5. Create the .env file
copy .env.example .env

# 6. (Optional) Edit .env and paste your Gemini API key
#    Open .env in notepad and set GOOGLE_API_KEY=your_key_here
#    Leave it empty to run in DEMO mode with sample data

# 7. Initialize the database (optional — it auto-creates on first run)
python database\db.py

# 8. (Optional) If upgrading from a previous version, run the migration
python database\migrate.py

# 9. Start the application
python app.py

# 9. Open your browser and go to:
#    http://127.0.0.1:5000
#    You will be redirected to the login page.
#    Click "Register" to create your first account.
```

### macOS / Linux (Terminal)

```bash
# 1. Navigate to the project folder
cd multi_agent_study_assistant

# 2. Create a virtual environment
python3 -m venv venv

# 3. Activate the virtual environment
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Create the .env file
cp .env.example .env

# 6. (Optional) Edit .env and paste your Gemini API key
#    Open .env in your editor and set GOOGLE_API_KEY=your_key_here
#    Leave it empty to run in DEMO mode with sample data

# 7. Initialize the database (optional — it auto-creates on first run)
python database/db.py

# 8. (Optional) If upgrading from a previous version, run the migration
python database/migrate.py

# 9. Start the application
python app.py

# 9. Open your browser and go to:
#    http://127.0.0.1:5000
#    You will be redirected to the login page.
#    Click "Register" to create your first account.
```

## Quick Start (TL;DR)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python app.py
# Go to http://127.0.0.1:5000 — register a new account to get started
```

## Usage Guide

1. **Register** — Create an account with a username and password (min 6 characters)
2. **Login** — Sign in with your credentials
3. **Upload Materials** — Go to "Study Materials" and upload a PDF/TXT file or type a topic
4. **Generate Summary** — Click "Full workflow" or "Summarize" on a material
5. **Take a Quiz** — Generate a quiz and answer the MCQs
6. **View Results** — See your score, correct/incorrect answers, and AI feedback
7. **Track Progress** — Visit "My Progress" to see charts and topic performance
8. **Weak Topic Quiz** — Generate a quiz focused on your weak topics
9. **Logout** — Click "Logout" in the sidebar when done

## Agents (separate modules, separate prompts and duties)

- **Summarizer** (`agents/summarizer_agent.py`): notes -> structured summary, no invented facts.
- **Quiz Generator** (`agents/quiz_agent.py`): conceptual MCQs, validates JSON (4 options, 1 answer) and retries if malformed.
- **Weak Topic Tracker** (`agents/weak_topic_agent.py`): rule-based classification over accumulated answers (needs 3+ answers per topic: >=75% Strong, >=50% Improving, else Needs Revision) + LLM/rule revision tips.
- **Orchestration** (`agents/study_graph.py`): LangGraph `StateGraph` with a shared state. START routes by stage: `summary`, `quiz`, `full` (summarize -> quiz), `evaluate` (track).

## Test each agent

```powershell
python -c "from agents import summarizer_agent as s; print(s.run(open('sample_notes.txt').read()))"
python -c "from agents import quiz_agent as q; print(q.generate(open('sample_notes.txt').read(), 5))"
python -c "from agents import weak_topic_agent as w; print(w.analyze([{'topic':'Overfitting','total':4,'correct':1}]))"
```

## Collaboration demo

Materials -> **Full workflow** -> take quiz (answer some wrong) -> results -> repeat 2-3 times -> **Weak-topic quiz**.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_API_KEY` | Gemini API key (leave empty for DEMO mode) | *(empty)* |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` |
| `SECRET_KEY` | Flask secret key for sessions | `dev` |

## Authentication

- **Password hashing**: Werkzeug's `generate_password_hash` / `check_password_hash` (PBKDF2)
- **Session management**: Flask built-in sessions (cookie-based)
- **Route protection**: `@login_required` decorator on all app routes
- **User isolation**: All data queries filtered by `user_id`

## Checklist

- [x] User registration and login/logout
- [x] Password hashing with Werkzeug
- [x] Session-based authentication
- [x] Upload TXT/PDF; invalid type, empty file, scanned PDF show errors
- [x] Summary generates and regenerates; quiz 5/10/15 works; navigation and submit work
- [x] Results show right/wrong + explanations; progress charts persist after restart
- [x] Topic shows "Not enough data" until 3 answers; delete material works

## Viva: workflow

Student registers and logs in -> uploads notes -> LangGraph runs Summarizer then Quiz Generator over shared state -> student attempts quiz -> answers saved in SQLite -> `evaluate` stage runs the Tracker on accumulated topic stats -> recommendations -> targeted quiz built from "Needs Revision" topics, closing the loop.

## Abstract

A web-based multi-user study assistant where three specialised AI agents, orchestrated with LangGraph, summarise student notes, generate and evaluate MCQ quizzes, and track topic-wise performance across attempts to give personalised revision guidance and targeted quizzes.

## Future work

Scanned-PDF OCR, spaced repetition, flashcards, vector search for long notes, export reports, multilingual notes, email verification, password reset.
