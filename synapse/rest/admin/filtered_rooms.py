# synapse/rest/admin/filtered_rooms.py

import logging
import re
from typing import TYPE_CHECKING, Tuple

from synapse.http.server import HttpServer
from synapse.http.servlet import RestServlet, parse_string
from synapse.http.site import SynapseRequest
from synapse.rest.admin._base import assert_user_is_admin
from synapse.types import JsonDict

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class FilteredRoomsServlet(RestServlet):
    """
    Новый эндпоинт для получения списка комнат, отфильтрованных
    по кастомной категории.
    GET /_synapse/admin/v1/rooms_by_category?category=space
    """
    PATTERNS = [re.compile("^/_synapse/admin/v1/rooms_by_category$")]

    def __init__(self, hs: "HomeServer"):
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.store = hs.get_datastores().main

    async def on_GET(self, request: SynapseRequest) -> Tuple[int, JsonDict]:
        requester = await self.auth.get_user_by_req(request)
        await assert_user_is_admin(self.auth, requester)

        category = parse_string(request, "category", required=True)

        rooms = await self.store.get_rooms_by_custom_category(category)

        return 200, {"rooms": rooms}


def register_servlets(hs: "HomeServer", http_server: HttpServer) -> None:
    FilteredRoomsServlet(hs).register(http_server)