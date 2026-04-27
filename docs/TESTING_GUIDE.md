# 🧪 Полное руководство по тестированию Phantom Dev

## 📋 Подготовка (один раз)

### 1. Проверь, что все сервисы запущены

**Cloud Run сервисы:**
```bash
gcloud run services list --project=phantom-dev-489603
```

Должны быть:
- ✅ `phantom-agent` (статус: Ready)
- ✅ `phantom-voice` (статус: Ready)

**Локальные сервисы:**
- ✅ Dashboard: `npm run dev` (должен быть запущен)
- ✅ Executor: будет запущен позже

---

## 🚀 Быстрый старт (каждый раз перед тестами)

### Шаг 1: Запустить Dashboard

```bash
cd dashboard
npm run dev
```

**Проверь:**
- Открой `http://localhost:3000` → должен загрузиться dashboard
- В консоли браузера (F12) должно быть: `WebSocket connected`

### Шаг 2: Запустить Executor

```bash
cd executor
PHANTOM_MODE=cloud python3 phantom.py
```

**Проверь в логах executor:**
- ✅ `GeminiClient initialised with Vertex AI — project=phantom-dev-489603`
- ✅ `Connected to agent at wss://...`
- ✅ `Phantom is online. Waiting for tasks...`

**Проверь в dashboard:**
- Должно появиться: **"1 executor connected"** (зелёный статус)

---

## 🎯 Тесты по уровням

### Уровень 1: Проверка подключений

#### Тест 1.1: Dashboard → Agent
1. Открой `http://localhost:3000`
2. Проверь статус: **"WebSocket connected"** (зелёный)
3. Если красный — проверь `.env.local` в `dashboard/`

#### Тест 1.2: Executor → Agent
1. Запусти executor (см. выше)
2. В логах executor должно быть: `Connected to agent at wss://...`
3. В dashboard должно быть: **"1 executor connected"**

#### Тест 1.3: Voice Gateway → Agent
```bash
curl https://phantom-voice-874381233509.us-central1.run.app/health
```

Должно вернуть: `{"status":"ok","active_session":false}`

---

### Уровень 2: Простые задачи (без executor)

#### Тест 2.1: Голосовая команда → Задача создана

1. Открой `http://localhost:3000/voice-test.html`
2. Нажми кнопку микрофона
3. Скажи: **"Hey Phantom, test task"**
4. Проверь:
   - ✅ В консоли браузера: `HTTP TASK DETECTED: test task (task_id=...)`
   - ✅ В dashboard: появилась новая задача со статусом `queued`
   - ✅ В логах voice gateway (см. ниже): `Task created in agent`

**Проверить логи voice gateway:**
```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20 | grep -E "stt-task|Task created"
```

**Проверить логи agent:**
```bash
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20 | grep -E "Task created"
```

---

### Уровень 3: Простые задачи (с executor)

#### Тест 3.1: Открыть приложение

**Команда:** "Hey Phantom, open Safari"

**Ожидаемое поведение:**
1. Executor получает задачу
2. Executor открывает Safari (через `open_app`)
3. Safari открывается на экране
4. Задача завершается со статусом `completed`

**Проверь:**
- ✅ В логах executor: `Executing: {'type': 'open_app', 'app_name': 'Safari'}`
- ✅ Safari открылся на экране
- ✅ В dashboard: статус задачи → `completed`

#### Тест 3.2: Открыть сайт

**Команда:** "Hey Phantom, open Google"

**Ожидаемое поведение:**
1. Executor открывает Google в браузере (через `open_url`)
2. Google открывается в новой вкладке
3. Задача завершается

**Проверь:**
- ✅ В логах executor: `Executing: {'type': 'open_url', 'url': 'https://www.google.com'}`
- ✅ Google открылся в браузере
- ✅ В dashboard: статус → `completed`

#### Тест 3.3: Поиск в Google

**Команда:** "Hey Phantom, open Google and search for Gemini"

**Ожидаемое поведение:**
1. Executor открывает Google
2. Executor находит поисковую строку и кликает по ней
3. Executor вводит "Gemini"
4. Executor нажимает Enter
5. Появляются результаты поиска
6. Задача завершается

**Проверь:**
- ✅ В логах executor: `Executing: {'type': 'open_url', ...}`
- ✅ Затем: `Executing: {'type': 'type', 'text': 'Gemini', ...}`
- ✅ Затем: `Executing: {'type': 'key_combo', 'keys': ['return']}`
- ✅ На экране: результаты поиска "Gemini"
- ✅ В dashboard: статус → `completed`

**Если executor не попадает по поисковой строке:**
- Проверь логи: возможно используется fallback метод (Tab навигация)
- Это нормально, если в итоге поиск выполнен

---

### Уровень 4: Сложные задачи (полный сценарий)

#### Тест 4.1: Поиск на YouTube

**Команда:** "Hey Phantom, open YouTube and search for Gemini AI"

**Ожидаемое поведение:**
1. Executor открывает YouTube
2. Executor находит поисковую строку
3. Executor вводит "Gemini AI"
4. Executor нажимает Enter
5. Появляются результаты поиска
6. Задача завершается

**Проверь:**
- ✅ Все шаги выполнены последовательно
- ✅ Результаты поиска видны на экране
- ✅ В dashboard: статус → `completed`

#### Тест 4.2: Многошаговая задача

**Команда:** "Hey Phantom, open Safari, then open Google, then search for Phantom Dev"

**Ожидаемое поведение:**
1. Executor открывает Safari
2. Executor открывает Google в Safari
3. Executor выполняет поиск "Phantom Dev"
4. Задача завершается

**Проверь:**
- ✅ Все шаги выполнены
- ✅ В dashboard: статус → `completed`

---

## 🔍 Как проверять логи во время теста

### В реальном времени (stream)

**Voice Gateway:**
```bash
gcloud run services logs tail phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603
```

**Agent:**
```bash
gcloud run services logs tail phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603
```

**Executor:**
- Логи видны прямо в терминале, где запущен executor

**Dashboard:**
- Открой DevTools (F12) → Console
- Все события WebSocket будут в консоли

---

## ❌ Типичные проблемы и решения

### Проблема 1: Executor не подключается

**Симптомы:**
- В dashboard: "No executor connected"
- В логах executor: ошибка подключения

**Решение:**
1. Проверь, что executor запущен
2. Проверь `.env` в `executor/`:
   - `AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/executor`
3. Проверь, что есть Application Default Credentials:
   ```bash
   gcloud auth application-default login --project=phantom-dev-489603
   ```

### Проблема 2: Voice Gateway возвращает 429

**Симптомы:**
- В логах voice gateway: `429 RESOURCE_EXHAUSTED`
- В консоли браузера: ошибка при отправке голосовой команды

**Решение:**
1. Проверь, что voice gateway использует Vertex AI:
   ```bash
   gcloud run services logs read phantom-voice \
     --region=us-central1 \
     --project=phantom-dev-489603 \
     --limit=20 | grep "Vertex AI"
   ```
2. Должно быть: `[/stt-task] Using Vertex AI — project=phantom-dev-489603`
3. Если нет — передеплой voice gateway (см. `DEPLOY_VERTEX_AI.md`)

### Проблема 3: Executor не выполняет действия

**Симптомы:**
- Executor получает задачу, но ничего не происходит на экране
- В логах executor: `Executing: ...` но действий нет

**Решение:**
1. Проверь macOS разрешения:
   - System Settings → Privacy & Security → Accessibility
   - Должен быть включён Terminal (или Python)
2. Проверь Input Monitoring:
   - System Settings → Privacy & Security → Input Monitoring
   - Должен быть включён Terminal (или Python)
3. Перезапусти executor после включения разрешений

### Проблема 4: Executor не попадает по поисковой строке

**Симптомы:**
- Executor пытается кликнуть, но кликает мимо поисковой строки
- В логах: координаты неверные

**Решение:**
1. Это нормально — executor использует fallback метод (Tab навигация)
2. Если поиск всё равно не выполняется:
   - Проверь, что браузер в фокусе
   - Проверь, что поисковая строка видна на экране
   - Попробуй увеличить экран (не zoom, а разрешение)

### Проблема 5: Задача не завершается

**Симптомы:**
- Executor выполняет все действия, но задача остаётся в статусе `running`
- В dashboard: статус не меняется на `completed`

**Решение:**
1. Проверь логи executor: должно быть `Task completed successfully`
2. Если нет — проверь `VERIFY_PROMPT` в `orchestrator.py`
3. Возможно, Gemini не распознаёт успешное выполнение
4. Попробуй более простую задачу для проверки

---

## 📊 Чеклист полного теста

### Перед каждым тестом:
- [ ] Dashboard запущен (`npm run dev`)
- [ ] Executor запущен (`python3 phantom.py`)
- [ ] В dashboard: "1 executor connected"
- [ ] В dashboard: WebSocket connected

### После каждого теста:
- [ ] Задача появилась в dashboard
- [ ] Статус задачи изменился на `completed` (или `failed` с понятной ошибкой)
- [ ] В логах executor: `Task completed successfully`
- [ ] На экране: визуально задача выполнена

---

## 🎬 Полный end-to-end тест

### Сценарий: "Открыть Google и найти Gemini"

1. **Запусти все компоненты:**
   - Dashboard: `npm run dev`
   - Executor: `python3 phantom.py`

2. **Проверь подключения:**
   - Dashboard: WebSocket connected ✅
   - Dashboard: 1 executor connected ✅

3. **Выполни голосовую команду:**
   - Открой `http://localhost:3000/voice-test.html`
   - Скажи: "Hey Phantom, open Google and search for Gemini"

4. **Наблюдай:**
   - В dashboard: задача появилась → статус `queued` → `running`
   - На экране: Google открывается → поисковая строка → ввод "Gemini" → Enter
   - В dashboard: статус → `completed`

5. **Проверь результат:**
   - На экране: результаты поиска "Gemini" видны
   - В dashboard: задача завершена успешно
   - В логах executor: `Task completed successfully`

---

## 🚀 Готово!

Теперь ты знаешь, как тестировать все компоненты Phantom Dev. Начни с **Уровня 1** и постепенно переходи к более сложным тестам.

**Совет:** Если что-то не работает, сначала проверь логи (см. `CHECK_LOGS.md`), затем разрешения macOS, затем подключения между компонентами.
