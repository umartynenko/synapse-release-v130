import logging
import re
from typing import TYPE_CHECKING, Tuple
from synapse.api.errors import AuthError, SynapseError
from synapse.http.server import HttpServer
from synapse.http.servlet import RestServlet
from synapse.http.site import SynapseRequest
from synapse.types import JsonDict

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)

# synapse/rest/admin/hierarchy_members.py - ИСПРАВЛЕННАЯ ВЕРСИЯ

import logging
import re
from typing import TYPE_CHECKING, Tuple

from synapse.api.errors import AuthError, SynapseError
from synapse.http.server import HttpServer
from synapse.http.servlet import RestServlet
from synapse.http.site import SynapseRequest
from synapse.types import JsonDict

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class HierarchyMembersServlet(RestServlet):
    """
    API для получения всех участников из ЧАТОВ внутри иерархии пространств.
    GET /_synapse/admin/v1/hierarchy_members/{room_id}
    """

    PATTERNS = [
        re.compile(f"/_synapse/admin/v1/hierarchy_members/(?P<room_id>[^/]+)$")
    ]

    def __init__(self, hs: "HomeServer"):
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.store = hs.get_datastores().main

    async def on_GET(
        self, request: SynapseRequest, room_id: str
    ) -> Tuple[int, JsonDict]:
        requester = await self.auth.get_user_by_req(request)
        is_admin = await self.auth.is_server_admin(requester)
        if not is_admin:
            raise AuthError(403, "You are not a server admin.")

        # --- ИЗМЕНЕННАЯ ЛОГИКА ---

        try:
            # 1. Получаем все дочерние пространства рекурсивно
            descendant_spaces = await self.store.get_all_descendant_spaces(room_id)

            # 2. Собираем ID всех пространств в иерархии (включая родительское)
            all_space_ids = [room_id] + descendant_spaces

            # 3. Для каждого пространства в иерархии находим его дочерние ЧАТЫ
            all_chat_ids: set[str] = set()
            for space_id in all_space_ids:
                # Используем существующий метод для получения дочерних комнат
                child_rooms = await self.store.get_children_with_chat_types(space_id)
                for child in child_rooms:
                    # Нас интересуют только чаты, а не вложенные пространства
                    if child.get("chat_type"):
                        all_chat_ids.add(child["room_id"])

            # 4. Получаем уникальных участников из всех найденных ЧАТОВ
            if not all_chat_ids:
                # Если чатов не найдено, возвращаем пустой список
                return 200, {"users": []}

            member_ids = await self.store.get_members_in_rooms(list(all_chat_ids))

        except Exception as e:
            logger.error(
                "Failed to get hierarchy members for %s: %s",
                room_id, e, exc_info=True
            )
            raise SynapseError(500, f"Failed to get hierarchy members: {e}")

        return 200, {"users": member_ids}


def register_servlets(hs: "HomeServer", http_server: HttpServer) -> None:
    HierarchyMembersServlet(hs).register(http_server)
    logger.info("HierarchyMembersServlet registered")
