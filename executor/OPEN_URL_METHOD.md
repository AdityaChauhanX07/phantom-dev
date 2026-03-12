# Открытие веб-сайтов: `open_url`

## Проблема

Executor пытался открыть веб-сайты (YouTube, Google, Jira) как приложения через `open_app`, что не работало, потому что это не установленные приложения.

## Решение

Добавлен новый тип действия `open_url`, который открывает веб-сайты в браузере:
- Работает с любыми веб-сайтами (YouTube, Google, Jira, Facebook, etc.)
- Автоматически открывает в браузере по умолчанию
- Не требует установленных приложений

## Как это работает

### Для Gemini:
Gemini теперь понимает разницу между:
- **Приложениями** (Calculator, TextEdit, Safari) → использует `open_app`
- **Веб-сайтами** (YouTube, Google, Jira) → использует `open_url`

### Для Executor:
Executor выполняет команду:
```bash
open "https://youtube.com"
```

Это автоматически откроет сайт в браузере по умолчанию.

## Примеры использования

### Веб-сайты (используют `open_url`):
- "open YouTube" → `{"type": "open_url", "url": "youtube.com"}`
- "open Google" → `{"type": "open_url", "url": "google.com"}`
- "open Jira" → `{"type": "open_url", "url": "jira.com"}`
- "open Facebook" → `{"type": "open_url", "url": "facebook.com"}`

### Приложения (используют `open_app`):
- "open Calculator" → `{"type": "open_app", "app_name": "Calculator"}`
- "open Safari" → `{"type": "open_app", "app_name": "Safari"}`
- "open TextEdit" → `{"type": "open_app", "app_name": "TextEdit"}`

## Как Gemini различает

1. **Веб-сайты**: YouTube, Google, Facebook, Twitter, Jira, etc.
   - Это известные веб-сервисы
   - Обычно имеют ".com" в названии
   - Используется `open_url`

2. **Приложения**: Calculator, TextEdit, Safari, Chrome, Finder, etc.
   - Это macOS приложения
   - Установлены на компьютере
   - Используется `open_app`

## Преимущества

1. **Работает везде** - не нужно устанавливать приложения
2. **Проще для Gemini** - не нужно искать иконки
3. **Надёжнее** - работает с любыми веб-сайтами
4. **Быстрее** - один шаг вместо нескольких

## Тестирование

```bash
cd executor
PHANTOM_MODE=cloud python3 phantom.py
```

Затем через curl:
```bash
curl -X POST https://phantom-agent-874381233509.us-central1.run.app/task \
  -H "Content-Type: application/json" \
  -d '{"goal": "open YouTube", "session_id": "test-123"}'
```

## Что ожидать

- Executor должен открыть YouTube в браузере одним действием
- Не должно быть попыток открыть "YouTube" как приложение
- Сайт должен открыться быстро (2-3 секунды)
