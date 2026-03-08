# phantom-dev

An AI-powered desktop automation agent that watches your screen and executes tasks using natural language instructions — backed by Gemini, streamed live to a Next.js dashboard.

---

## TODO: Setup Instructions

- [ ] Copy `.env.example` to `.env` and fill in all values
- [ ] Install Python dependencies: `pip install -r agent/requirements.txt` and `pip install -r executor/requirements.txt`
- [ ] Install dashboard dependencies: `cd dashboard && npm install`
- [ ] (Optional) Provision GCP infrastructure: `cd infra && terraform init && terraform apply`
- [ ] Run locally with Docker Compose: `docker compose up --build`
- [ ] Run dashboard dev server: `cd dashboard && npm run dev`

## Architecture

```
User prompt
    │
    ▼
Next.js Dashboard  ──WebSocket──▶  Agent (Cloud Run / FastAPI)
                                        │
                                        │  Gemini API
                                        │  (task planning)
                                        │
                                   WebSocket ──▶ Executor (local)
                                                    │
                                              mss capture
                                              pyautogui actions
```

## Project Structure

| Path | Description |
|------|-------------|
| `agent/` | FastAPI backend — task planning with Gemini, deployed to Cloud Run |
| `executor/` | Local Python process — screen capture and action execution |
| `dashboard/` | Next.js 14 real-time frontend |
| `infra/` | Terraform IaC for Cloud Run, Firestore |
