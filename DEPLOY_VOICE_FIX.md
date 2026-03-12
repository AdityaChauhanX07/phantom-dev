# Исправление: Деплой Voice Gateway с правильными настройками

## Проблема

В логах видно:
- ❌ `GeminiLiveGateway using Vertex AI` (старый код)
- ❌ `GEMINI_API_KEY is not set` (ключ не установлен)
- ❌ Ошибка 1008 при попытке использовать Live API через Vertex AI

## Решение

### 1. Убедись, что GEMINI_API_KEY установлен

```bash
# Проверь, есть ли ключ в окружении
echo $GEMINI_API_KEY

# Если нет, установи его (замени на свой ключ)
export GEMINI_API_KEY="твой_ключ_здесь"
```

### 2. Задеплой обновлённый код

```bash
./deploy-voice.sh
```

Скрипт автоматически:
- Соберёт Docker image с исправленным кодом
- Установит `GEMINI_API_KEY` в Cloud Run
- Установит `GCP_PROJECT_ID` для `/stt-task` (Vertex AI)

### 3. Проверь деплой

```bash
gcloud run services describe phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --format="value(spec.template.spec.containers[0].env)" | grep -E "GEMINI_API_KEY|GCP_PROJECT_ID"
```

Должно показать:
- `GEMINI_API_KEY=...` ✅
- `GCP_PROJECT_ID=phantom-dev-489603` ✅

### 4. Проверь логи

```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

**Ожидаемые логи:**
- ✅ `GeminiLiveGateway using API key for Live API` (не Vertex AI!)
- ✅ `[/stt-task] Using Vertex AI — project=phantom-dev-489603` (для /stt-task)
- ❌ НЕ должно быть: `GEMINI_API_KEY is not set`

---

## Итоговая схема

- **Live API (WebSocket `/stream`)** → использует `GEMINI_API_KEY` ✅
- **`/stt-task` endpoint** → использует Vertex AI (`GCP_PROJECT_ID`) ✅

---

## Если GEMINI_API_KEY не установлен

1. Получи ключ: https://aistudio.google.com/apikey
2. Установи в окружении:
   ```bash
   export GEMINI_API_KEY="твой_ключ"
   ```
3. Задеплой:
   ```bash
   ./deploy-voice.sh
   ```

**Готово!** 🚀
