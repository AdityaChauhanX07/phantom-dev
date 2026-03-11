# Исправление: Приоритет Dock вместо Spotlight/Finder

## Проблема

Executor пытался использовать сложные методы (Finder, Spotlight, Command+Shift+A) вместо простого клика по иконке в Dock. Это приводило к:
- Открытию Spotlight без дальнейших действий
- Попыткам использовать Command+Shift+A в неправильном контексте (например, в Firefox)
- Множественным неудачным попыткам

## Что исправлено

1. **DECOMPOSE_PROMPT**: Теперь Gemini понимает, что для "open Calculator" нужно создать ОДИН простой шаг: "Click on Calculator icon in Dock"
2. **NEXT_ACTION_PROMPT**: Приоритет Dock - сначала искать иконку в Dock, только потом использовать Finder
3. **ALTERNATIVE_ACTION_PROMPT**: При неудаче тоже использовать Dock, а не Spotlight

## Как протестировать

### Простые команды (должны работать быстро):

1. **"open Calculator"** - самое простое, должно быть 1 шаг
2. **"open Safari"** - если Safari в Dock
3. **"open TextEdit"** - если TextEdit в Dock

### Запуск:

```bash
cd executor
PHANTOM_MODE=cloud python3 phantom.py
```

Затем через voice-test.html или curl:
```bash
curl -X POST https://phantom-agent-874381233509.us-central1.run.app/task \
  -H "Content-Type: application/json" \
  -d '{"goal": "open Calculator", "session_id": "test-123"}'
```

## Что ожидать

- Executor должен сразу искать иконку в Dock
- Для простых задач типа "open Calculator" должно быть 1-2 шага максимум
- Не должно быть попыток использовать Command+Shift+A или Spotlight

## Если всё ещё не работает

1. Убедись, что иконка приложения видна в Dock на скриншоте
2. Если иконки нет в Dock - добавь её туда вручную (перетащи из Applications)
3. Проверь логи - там видно, какие шаги генерирует Gemini
