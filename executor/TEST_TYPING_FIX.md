# Исправление проблемы с печатью текста

## Что исправлено

1. **Промпт улучшен**: Gemini теперь понимает, что для задач "Type X into Y" нужно возвращать action с типом "type", включая координаты поля (x, y) и текст.

2. **Автоматический клик + печать**: Executor теперь автоматически:
   - Кликает на координаты поля (если указаны)
   - Выделяет весь существующий текст (Cmd+A)
   - Печатает новый текст

## Как протестировать

### Простые команды для теста:

1. **Открыть Calculator** (самое простое):
   ```
   "open Calculator"
   ```

2. **Открыть TextEdit и напечатать**:
   ```
   "open TextEdit and type Hello World"
   ```

3. **Открыть Safari и перейти на сайт** (сложнее):
   ```
   "open Safari and go to google.com"
   ```

### Запуск:

```bash
cd executor
PHANTOM_MODE=cloud python3 phantom.py
```

Затем в voice-test.html или через curl:
```bash
curl -X POST https://phantom-agent-874381233509.us-central1.run.app/task \
  -H "Content-Type: application/json" \
  -d '{"goal": "open Calculator", "session_id": "test-123"}'
```

## Что ожидать

- Executor должен кликать на нужные элементы
- Для задач с печатью - должен автоматически кликать на поле, выделять текст, и печатать
- Должно работать быстрее (задержки уменьшены)

## Если не работает

1. Проверь разрешения macOS (Accessibility + Input Monitoring)
2. Проверь логи executor - там видно, какие действия выполняются
3. Попробуй более простую команду (например, "open Calculator")
