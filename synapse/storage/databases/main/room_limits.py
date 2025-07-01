from synapse.storage._base import SQLBaseStore
from synapse.storage.database import DatabasePool
from synapse.types import JsonDict
from typing import Optional


class RoomLimitsStore(SQLBaseStore):
    """Хранилище для работы с лимитами комнат (пространств)."""

    async def set_room_limits(
        self, room_id: str, max_users: Optional[int], max_chats: Optional[int]
    ) -> None:
        """
        Устанавливает или обновляет лимиты для комнаты.
        Использует ON CONFLICT для атомарной операции upsert.
        """
        await self.db_pool.simple_upsert(
            table="room_limits",
            keyvalues={"room_id": room_id},
            values={"max_users": max_users, "max_chats": max_chats},
            desc="set_room_limits",
        )

    async def get_room_limits(self, room_id: str) -> Optional[JsonDict]:
        """
        Получает лимиты для указанной комнаты.
        Возвращает словарь {max_users: int, max_chats: int} или None.
        """
        # Используем simple_select_one_onecol для получения значений по отдельности
        max_users = await self.db_pool.simple_select_one_onecol(
            table="room_limits",
            keyvalues={"room_id": room_id},
            retcol="max_users",
            allow_none=True,
            desc="get_room_limits_max_users",
        )

        max_chats = await self.db_pool.simple_select_one_onecol(
            table="room_limits",
            keyvalues={"room_id": room_id},
            retcol="max_chats",
            allow_none=True,
            desc="get_room_limits_max_chats",
        )

        # Если оба значения None - лимитов нет
        if max_users is None and max_chats is None:
            return None

        return {"max_users": max_users, "max_chats": max_chats}

    async def delete_room_limits(self, room_id: str) -> None:
        """Удаляет лимиты для комнаты."""
        await self.db_pool.simple_delete(
            table="room_limits",
            keyvalues={"room_id": room_id},
            desc="delete_room_limits",
        )