-- Файл: synapse/storage/schema/main/delta/93/01_room_limits.sql

-- Таблица для хранения кастомных лимитов для комнат (пространств)
CREATE TABLE IF NOT EXISTS room_limits (
    room_id TEXT PRIMARY KEY,
    max_users BIGINT,
    max_chats BIGINT,

    -- Связываем с существующей таблицей rooms, чтобы обеспечить целостность данных.
    -- При удалении комнаты из таблицы rooms, запись из room_limits удалится автоматически.
    CONSTRAINT room_limits_room_id_fkey FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE CASCADE
);

-- Индекс для быстрого поиска по room_id (хотя PRIMARY KEY уже создает его, явное создание не помешает)
CREATE UNIQUE INDEX IF NOT EXISTS room_limits_room_id_key ON room_limits(room_id);