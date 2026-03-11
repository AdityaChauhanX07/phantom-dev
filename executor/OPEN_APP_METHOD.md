# Новый метод открытия приложений: `open_app`

## Проблема

Открытие приложений через Dock было слишком сложным для Gemini:
- Нужно было видеть иконку в Dock на скриншоте
- Нужно было точно определить координаты иконки
- Если иконка не видна или скрыта - не работает

## Решение

Добавлен новый тип действия `open_app`, который использует команду macOS `open -a`:
- Не требует видеть иконку в Dock
- Не требует координаты
- Работает даже если приложение не в Dock
- Намного проще для Gemini

## Как это работает

### Для Gemini:
Вместо сложного поиска иконки в Dock, Gemini просто возвращает:
```json
{"type": "open_app", "app_name": "Calculator"}
```

### Для Executor:
Executor выполняет команду:
```bash
open -a "Calculator"
```

Это гарантированно откроет приложение, если оно установлено.

## Примеры использования

### Простые команды:
- "open Calculator" → `{"type": "open_app", "app_name": "Calculator"}`
- "open Safari" → `{"type": "open_app", "app_name": "Safari"}`
- "open Chrome" → `{"type": "open_app", "app_name": "Google Chrome"}`

### Имена приложений:
- Calculator → "Calculator"
- Safari → "Safari"
- Chrome → "Google Chrome"
- Firefox → "Firefox"
- TextEdit → "TextEdit"
- Finder → "Finder"

## Преимущества

1. **Проще для Gemini** - не нужно искать иконки
2. **Надёжнее** - работает даже если иконка не видна
3. **Быстрее** - один шаг вместо нескольких
4. **Точнее** - не нужно определять координаты

## Тестирование

```bash
cd executor
PHANTOM_MODE=cloud python3 phantom.py
```

Затем через curl:
```bash
curl -X POST https://phantom-agent-874381233509.us-central1.run.app/task \
  -H "Content-Type: application/json" \
  -d '{"goal": "open Calculator", "session_id": "test-123"}'
```

## Что ожидать

- Executor должен открыть Calculator одним действием
- Не должно быть попыток искать иконку в Dock
- Не должно быть попыток использовать Spotlight или Finder
- Приложение должно открыться быстро (1-2 секунды)
