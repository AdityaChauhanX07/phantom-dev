# Пошаговая инструкция: Деплой с Vertex AI

## Шаг 1: Обновить executor/.env

Executor уже поддерживает Vertex AI! Нужно добавить GCP_PROJECT_ID.

**Отредактируй `executor/.env`:**

```bash
# Вариант 1: Использовать Vertex AI (рекомендуется, нет rate limit)
GCP_PROJECT_ID=phantom-dev-489603
GCP_LOCATION=us-central1
AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/executor
PHANTOM_MODE=cloud

# Вариант 2: Использовать API key (fallback, есть rate limit)
# GEMINI_API_KEY=твой_ключ
# AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/executor
# PHANTOM_MODE=cloud
```

**Важно:** 
- Если есть `GCP_PROJECT_ID` — executor использует Vertex AI (нет rate limit)
- Если нет `GCP_PROJECT_ID`, но есть `GEMINI_API_KEY` — использует AI Studio (есть rate limit)
- Можно оставить оба, но приоритет у `GCP_PROJECT_ID`

---

## Шаг 2: Проверить dashboard/.env.local

Dashboard НЕ использует Gemini напрямую, только WebSocket для связи с agent.

**Проверь `dashboard/.env.local`:**

```bash
NEXT_PUBLIC_AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/dashboard
```

**Ничего менять не нужно!** Dashboard только получает события от agent через WebSocket.

---

## Шаг 3: Задеплоить voice gateway

Voice gateway теперь использует Vertex AI для `/stt-task`.

**Запусти:**

```bash
./deploy-voice.sh
```

Этот скрипт:
1. Соберёт Docker image
2. Запушит в Artifact Registry
3. Задеплоит на Cloud Run с правильными env vars

**Env vars в Cloud Run (устанавливаются автоматически):**
- `GCP_PROJECT_ID=phantom-dev-489603` ✅
- `GCP_LOCATION=us-central1` ✅
- `GEMINI_API_KEY=...` (для Live API fallback, если нужно)
- `AGENT_URL=...`
- `TEXT_MODEL=gemini-2.5-flash`
- `LIVE_MODEL=gemini-2.5-flash-native-audio-preview-12-2025`

---

## Шаг 4: Проверить деплой

**Проверь логи voice gateway:**

```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

**Ищи в логах:**
- `[/stt-task] Using Vertex AI — project=phantom-dev-489603 location=us-central1` ✅
- Больше НЕ должно быть ошибок `429 RESOURCE_EXHAUSTED` ✅

---

## Шаг 5: Протестировать

### 5.1. Запустить dashboard (если ещё не запущен)

```bash
cd dashboard
npm run dev
```

Открой: `http://localhost:3000`

### 5.2. Запустить executor

```bash
cd executor
PHANTOM_MODE=cloud python3 phantom.py
```

**Проверь логи executor:**
- Должно быть: `GeminiClient initialised with Vertex AI — project=phantom-dev-489603`
- НЕ должно быть: `GeminiClient falling back to AI Studio key`

### 5.3. Протестировать голосовую команду

1. Открой: `http://localhost:3000/voice-test.html`
2. Нажми кнопку микрофона
3. Скажи: "Hey Phantom, test task"
4. Проверь:
   - ✅ В логах voice gateway: `Using Vertex AI`
   - ✅ В dashboard: появилась новая задача
   - ✅ НЕТ ошибки 429

---

## Итоговая схема

```
┌─────────────────┐
│  voice-test.html │
│  (браузер)      │
└────────┬────────┘
         │ HTTP POST /stt-task
         ▼
┌─────────────────┐
│  Voice Gateway  │
│  (Cloud Run)    │
│  Vertex AI ✅   │
└────────┬────────┘
         │ POST /task
         ▼
┌─────────────────┐
│  Agent          │
│  (Cloud Run)    │
└────────┬────────┘
         │ WebSocket
         ├──────────────┐
         ▼              ▼
┌─────────────┐  ┌─────────────┐
│  Executor   │  │  Dashboard  │
│  Vertex AI ✅│  │  (локально) │
│  (локально) │  │             │
└─────────────┘  └─────────────┘
```

**Все используют Vertex AI:**
- ✅ Voice Gateway `/stt-task` → Vertex AI
- ✅ Executor → Vertex AI

**НЕ используют Gemini:**
- ✅ Dashboard (только WebSocket для событий)

---

## Troubleshooting

### Executor всё ещё использует API key

**Проблема:** В логах видно `GeminiClient falling back to AI Studio key`

**Решение:** Проверь `executor/.env`:
```bash
GCP_PROJECT_ID=phantom-dev-489603  # Должно быть!
GCP_LOCATION=us-central1
```

### Voice gateway всё ещё 429

**Проблема:** Всё ещё ошибки 429

**Решение:** 
1. Проверь логи: должно быть `Using Vertex AI`
2. Если нет — перезадеплой: `./deploy-voice.sh`
3. Проверь, что Vertex AI API включен: `gcloud services list --enabled --project=phantom-dev-489603 | grep aiplatform`

### Dashboard не подключается

**Проблема:** Dashboard показывает "Disconnected"

**Решение:** Проверь `dashboard/.env.local`:
```bash
NEXT_PUBLIC_AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/dashboard
```

---

## Готово! 🚀

После выполнения всех шагов:
- ✅ Voice gateway использует Vertex AI (нет rate limit)
- ✅ Executor использует Vertex AI (нет rate limit)
- ✅ Dashboard подключён к agent
- ✅ Можно тестировать голосовые команды

**Начинай с Шага 1!**
