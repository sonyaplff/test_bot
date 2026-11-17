# Telegram-бот студии ногтевого сервиса (PostgreSQL)

Версия исходного учебного Telegram-бота с сохранением записей в PostgreSQL, а не в SQLite.
Сохранены выбор мастера, услуги, даты, времени, подтверждение и отмена записи.

## Шаг 1. Создать базу

Установить PostgreSQL и pgAdmin 4. В pgAdmin создать базу `nail_studio` (Databases → Create → Database).
Выбрать `nail_studio` → Tools → Query Tool → открыть `schema.sql` → Execute.
**Внимание:** `schema.sql` удаляет существующие учебные таблицы и данные при повторном запуске.
Затем **один раз** открыть и выполнить `seed.sql` (примерные данные).

## Шаг 2. Настроить бота

1. Сохранить исходную папку работающего бота как резервную копию. Старый `nail_studio.db` не удалять.
2. Открыть эту новую папку в VS Code.
3. В терминале Windows: `py -m pip install -r requirements.txt`
4. Скопировать `.env.example` в `.env`.
5. В `.env` вписать **тот же** `BOT_TOKEN`, что использовался у предыдущего бота, и пароль PostgreSQL в `PGPASSWORD`.
   `PGUSER=postgres`, `PGHOST=localhost`, `PGPORT=5432`, `PGDATABASE=nail_studio` оставить, если при установке их не меняли.
   Не публиковать `.env`, токен и пароль.
6. Остановить прежний запущенный процесс бота (Ctrl+C), чтобы не было двух одновременных экземпляров с одним токеном.
7. Запустить `py bot.py`.

## Шаг 3. Проверить

В Telegram написать существующему боту `/start`, выбрать мастера, услугу, день и время.
В pgAdmin открыть Query Tool и выполнить:

```sql
SELECT b.id, c.full_name AS client, m.full_name AS master,
       s.title AS service, b.visit_date, b.starts_at,
       b.ends_at, b.status
FROM bookings b
JOIN clients c ON c.id=b.client_id
JOIN masters m ON m.id=b.master_id
JOIN services s ON s.id=b.service_id
ORDER BY b.id DESC;
```

Новая запись должна появиться в PostgreSQL. В боте нажать «Мои записи», проверить отмену; в БД статус изменится на `cancelled`.

## Важные отличия

- Исходный бот использовал SQLite (`nail_studio.db`). Эта версия использует PostgreSQL и не переносит старые записи автоматически.
- В PostgreSQL поля называются `full_name`, `title`, `duration_min`, `starts_at`, `ends_at`.
- Номера телефонов должны быть российскими в формате `+7XXXXXXXXXX`.
- Все проверки пересечений дополнительно защищены ограничением EXCLUDE в PostgreSQL.
- Не запускайте одновременно старую и новую версии с одним Telegram-токеном.
- Если вы уже меняли код бота самостоятельно, сравните его с этой версией: она адаптирована из ранее подготовленного `bot.py`.
