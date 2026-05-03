# Communication CoachBot Platform

A Django MVP for five communication-training CoachBots:

1. Conflict CoachBot
2. RISE CoachBot
3. DESC CoachBot
4. PAUSE CoachBot
5. SEA CoachBot

It supports user login, five selectable CoachBots, selectable Ollama model inside chat, conversation history, a user dashboard, a staff/admin analytics dashboard, and Railway-ready deployment files.

## Local setup

```bash
cd coachbot_platform
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_bots
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000`.

## Run Ollama locally

```bash
ollama pull llama3.1
ollama pull mistral
ollama pull qwen2.5
ollama pull gemma2
ollama pull phi3
ollama serve
```

Set this in `.env`:

```bash
OLLAMA_BASE_URL=http://localhost:11434
```

## Railway deployment

Create a Railway project with:

- Django service from this repo
- PostgreSQL service
- Ollama service if you want hosted Ollama

Set environment variables:

```bash
SECRET_KEY=your-secret-key
DEBUG=False
DATABASE_URL=Railway PostgreSQL URL
OLLAMA_BASE_URL=http://your-ollama-service:11434
ALLOWED_HOSTS=your-app.up.railway.app
```

The included `railway.json` runs migrations, seeds bots, and starts Gunicorn.

## Production next steps

Before real learners use it, add consent language, privacy policy, de-identification warnings, export/delete conversation options, rate limiting, and stronger production security settings.
=======
# coachbot-platform
Practice difficult conversations with Conflict, RISE, DESC, PAUSE, and SEA CoachBots.

