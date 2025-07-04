# synapse/rest/admin/room_children.py

import logging
import re
from typing import TYPE_CHECKING, Tuple


from synapse.api.errors import SynapseError
from synapse.http.server import HttpServer
from synapse.http.servlet import RestServlet, parse_string
from synapse.http.site import SynapseRequest
from synapse.rest.admin._base import assert_user_is_admin
from synapse.types import JsonDict

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class RoomChildrenServlet(RestServlet):
    """
    Новый эндпоинт для получения дочерних чатов пространства и их типов.
    GET /_synapse/admin/v1/room_children/{room_id}
    """
    # ИЗМЕНЕНИЕ: Для RestServlet обязательно нужно определить PATTERNS
    PATTERNS = [re.compile("^/_synapse/admin/v1/room_children/(?P<room_id>[^/]+)$")]

    def __init__(self, hs: "HomeServer"):
        # ИЗМЕНЕНИЕ: У RestServlet конструктор без аргументов
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()  # Получаем auth здесь
        self.store = hs.get_datastores().main

    async def on_GET(self, request: SynapseRequest, room_id: str) -> Tuple[
        int, JsonDict]:
        # Получаем пользователя и проверяем права администратора
        requester = await self.auth.get_user_by_req(request)
        await assert_user_is_admin(self.auth, requester)

        children = await self.store.get_children_with_chat_types(room_id)

        return 200, {"children": children}


def register_servlets(hs: "HomeServer", http_server: HttpServer) -> None:
    RoomChildrenServlet(hs).register(http_server)