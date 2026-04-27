# Как проверить логи всех компонентов

## 1. Voice Gateway (Cloud Run)

```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=50
```

**Что искать:**
- ✅ `GeminiLiveGateway using API key for Live API`
- ✅ `[/stt-task] Using Vertex AI — project=phantom-dev-489603`
- ✅ `Task created in agent — task_id=...`
- ❌ НЕТ ошибок `429` или `1008`

**Последние 20 строк:**
```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

---

## 2. Agent (Cloud Run)

```bash
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=50
```

**Что искать:**
- ✅ `[POST /task] Task created — task_id=...`
- ✅ `[WS /ws/executor] Task dispatched to executor`
- ✅ `connected_executors: 1` (если executor подключён)

**Последние 20 строк:**
```bash
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

---

## 3. Executor (локально, в терминале)

**Логи видны прямо в терминале, где запущен executor.**

**Что искать:**
- ✅ `GeminiClient initialised with Vertex AI — project=phantom-dev-489603`
- ✅ `Connected to agent at wss://...`
- ✅ `Phantom is online. Waiting for tasks...`
- ✅ `Received task: '...'`
- ✅ `Executing: {'type': 'click', ...}`
- ❌ НЕТ ошибок `Your default credentials were not found`

**Если нужно сохранить логи в файл:**
```bash
cd executor
PHANTOM_MODE=cloud python3 /Users/vladimirkhegai/Desktop/gemini_hackathon/phantom-dev/executor/phantom.py 2>&1 | tee executor.log
```

---

## 4. Dashboard (в браузере)

**Открой DevTools (F12) → Console**

**Что искать:**
- ✅ `WebSocket connected`
- ✅ `Received event: task_queued`
- ✅ `Received event: task_result`
- ❌ НЕТ ошибок WebSocket

**Network tab:**
- Проверь WebSocket connection к agent
- Должен быть статус `101 Switching Protocols`

---

## Быстрые команды (скопируй и вставь)

### Все логи за последние 5 минут

```bash
# Voice gateway
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=50

# Agent
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=50
```

### Только ошибки

```bash
# Voice gateway (только ERROR)
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=100 | grep ERROR

# Agent (только ERROR)
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=100 | grep ERROR
```

### Следить за логами в реальном времени

```bash
# Voice gateway (stream)
gcloud run services logs tail phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603

# Agent (stream)
gcloud run services logs tail phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603
```

---

## Что проверять после голосовой команды

### 1. Voice Gateway

```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=30 | grep -E "stt-task|Task created"
```

**Должно быть:**
- `[/stt-task] Using Vertex AI`
- `Task created in agent — task_id=...`

### 2. Agent

```bash
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=30 | grep -E "Task created|dispatched"
```

**Должно быть:**
- `[POST /task] Task created — task_id=...`
- `[WS /ws/executor] Task dispatched to executor`

### 3. Executor

**В терминале executor должно быть:**
- `Received task: '...'`
- `GeminiClient initialised with Vertex AI`
- `Executing: ...`
- `Task completed successfully`

---

## Troubleshooting

### Нет логов в Cloud Run

**Проверь, что сервисы запущены:**
```bash
gcloud run services list --project=phantom-dev-489603
```

### Executor не показывает логи

**Проверь, что executor запущен:**
- Должно быть: `Phantom is online. Waiting for tasks...`

### Dashboard не показывает события

**Проверь консоль браузера (F12):**
- Должно быть: `WebSocket connected`
- НЕТ ошибок WebSocket

---

## Готово! 🚀

Теперь ты знаешь, как проверить логи всех компонентов системы.
