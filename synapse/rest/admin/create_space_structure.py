# synapse/rest/admin/create_space_structure.py

import logging
from typing import TYPE_CHECKING, Tuple, List, Dict, Any, Optional
import re

from synapse.api.errors import SynapseError, Codes
from synapse.api.room_versions import RoomVersion
from synapse.http.server import HttpServer
from synapse.http.servlet import RestServlet
from synapse.http.site import SynapseRequest
from synapse.types import Requester, create_requester
from synapse.util.stringutils import random_string
from synapse.rest.admin._base import admin_patterns

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class CreateSpaceStructureServlet(RestServlet):
    """
    API для атомарного создания дерева пространств с чатами и делегированием прав.
    Принимает POST-запрос с JSON-телом:
    {
        "creator_id": "@user:server.com", // Пользователь, которому делегируются права
        "main_space": {
            "name": "Главное пространство",
            "topic": "Тема",
            "alias_localpart": "main-space" // опционально
        },
        "preset": "private_chat", // или "public_chat"
        "subspaces": [ // Дерево подпространств
            { "name": "Подпространство 1", "subspaces": [] },
            { "name": "Подпространство 2", "subspaces": [
                { "name": "Вложенное 2.1", "subspaces": [] }
            ]}
        ]
    }
    """
    PATTERNS = admin_patterns("/create_space_structure$")

    def __init__(self, hs: "HomeServer"):
        self.hs = hs
        self.auth = hs.get_auth()
        self.room_creation_handler = hs.get_room_creation_handler()
        self.room_member_handler = hs.get_room_member_handler()
        self.event_creation_handler = hs.get_event_creation_handler()

    async def on_POST(self, request: SynapseRequest) -> Tuple[int, Dict[str, Any]]:
        # Аутентификация: только администраторы сервера могут вызывать этот эндпоинт
        requester = await self.auth.get_user_by_req(request)
        await self.auth.is_server_admin(requester, allow_appservice=True)

        content = self.parse_json_body(request)

        admin_creator_requester = requester  # Админ, который выполняет действия
        delegated_user_id = content.get("creator_id")
        main_space_data = content["main_space"]
        subspaces_tree = content.get("subspaces", [])
        preset = content.get("preset", "private_chat")

        if not delegated_user_id:
            raise SynapseError(400, "'creator_id' is required", Codes.MISSING_PARAM)

        delegated_requester = create_requester(delegated_user_id)

        # Рекурсивная функция, которая делает всю работу
        async def create_and_delegate_recursive(
            space_node: Dict, parent_id: Optional[str]
        ) -> None:
            if not space_node.get("name"):
                return

            # 1. Создаем пространство от имени админа
            room_config = {
                "preset": preset,
                "name": space_node["name"],
                "topic": space_node.get("topic", ""),
                "creation_content": {"type": "m.space"},
            }
            if space_node.get("alias_localpart"):
                room_config["room_alias_name"] = space_node["alias_localpart"]

            # Используем внутренний метод, чтобы избежать рекурсии с нашим кастомным кодом
            new_room_id, _, _ = await self.room_creation_handler.create_room(
                requester=admin_creator_requester,
                config=room_config,
                ratelimit=False
            )
            logger.info(f"Создано пространство: {new_room_id}")

            # 2. Делегируем права и присоединяем пользователя
            if delegated_user_id != admin_creator_requester.user.to_string():
                # Приглашаем пользователя от имени админа
                await self.room_member_handler.update_membership(
                    requester=admin_creator_requester,
                    target=delegated_requester.user,
                    room_id=new_room_id,
                    action="invite",
                    ratelimit=False
                )
                # Заставляем пользователя присоединиться
                await self.room_member_handler.update_membership(
                    requester=delegated_requester,
                    target=delegated_requester.user,
                    room_id=new_room_id,
                    action="join",
                    ratelimit=False
                )
                # Делаем пользователя админом комнаты
                await self.room_creation_handler.hs.get_room_power_levels_handler().set_power_level(
                    room_id=new_room_id,
                    user_id=delegated_user_id,
                    power_level=100,
                    requester=admin_creator_requester
                )

            # 3. Привязываем к родителю
            if parent_id:
                await self.event_creation_handler.create_and_send_nonmember_event(
                    requester=admin_creator_requester,
                    event_dict={
                        "type": "m.space.child",
                        "state_key": new_room_id,
                        "room_id": parent_id,
                        "content": {"via": [self.hs.hostname], "suggested": True},
                    },
                    ratelimit=False
                )

            # 4. Рекурсия для дочерних
            if "subspaces" in space_node and space_node["subspaces"]:
                for child_node in space_node["subspaces"]:
                    await create_and_delegate_recursive(child_node, new_room_id)

        # --- ЗАПУСК ПРОЦЕССА ---
        await create_and_delegate_recursive(main_space_data, None)

        # Запуск для подпространств верхнего уровня
        # Это надо будет переделать, чтобы главное пространство было корнем дерева
        # Пока для простоты создаем их на одном уровне
        for subspace in subspaces_tree:
            await create_and_delegate_recursive(subspace, None)

        return 200, {"message": "Space structure created successfully."}


def register_servlets(hs: "HomeServer", http_server: HttpServer):
    CreateSpaceStructureServlet(hs).register(http_server)
