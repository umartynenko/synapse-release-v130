# synapse/rest/admin/space_management.py

import logging
from typing import TYPE_CHECKING, Tuple

from synapse.api.constants import Membership
from synapse.api.errors import AuthError, Codes, SynapseError
from synapse.http.server import HttpServer
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.http.site import SynapseRequest
from synapse.rest.admin._base import admin_patterns
# <<< ИЗМЕНЕНИЕ: Добавляем импорт create_requester >>>
from synapse.types import JsonMapping, Requester, UserID, create_requester

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)

# Определяем тип нашего кастомного события состояния.
SUBSCRIBER_ADMIN_EVENT_TYPE = "dev.martynenko.space.subscriber_admins"


class SpaceSubscriberAdminHandler:
    """
    Обработчик логики для назначения "Абонентов Администраторов" в пространствах.
    """

    def __init__(self, hs: "HomeServer"):
        self.hs = hs
        self.auth = hs.get_auth()
        # <<< ИЗМЕНЕНИЕ: Убираем self.store, так как он не имеет нужных методов >>>
        self.event_creation_handler = hs.get_event_creation_handler()
        self.room_member_handler = hs.get_room_member_handler()
        # <<< ИЗМЕНЕНИЕ: Получаем контроллер состояния напрямую >>>
        self._state_controller = hs.get_storage_controllers().state

    async def add_subscriber_admin(
        self, space_id: str, user_id: str, requester: "Requester"
    ):
        """
        Добавляет пользователя в список "Абонент Администратор" для пространства.
        1. Проверяет права серверного администратора.
        2. Присоединяет пользователя к пространству, если его там нет.
        3. Обновляет или создает событие состояния 'dev.martynenko.space.subscriber_admins'.
        """
        if not await self.auth.is_server_admin(requester):
            raise AuthError(403, "You must be a server admin to use this endpoint")

        target_user = UserID.from_string(user_id)

        # <<< ИЗМЕНЕНИЕ: Создаем "привилегированного" реквестера от имени админа >>>
        # Это необходимо, чтобы обойти проверку "нельзя заставить другого пользователя присоединиться".
        admin_requester = create_requester(
            requester.user, authenticated_entity=requester.user.to_string()
        )

        try:
            # <<< ИЗМЕНЕНИЕ: Используем admin_requester для выполнения действия >>>
            await self.room_member_handler.update_membership(
                requester=admin_requester,
                target=target_user,
                room_id=space_id,
                action=Membership.JOIN,
            )
            logger.info("Joined user %s to space %s to make them a subscriber admin.",
                        user_id, space_id)
        except SynapseError as e:
            # Игнорируем ошибку, если пользователь уже в комнате или действие запрещено,
            # но не другие потенциальные проблемы.
            if e.errcode != Codes.FORBIDDEN and "already in room" not in e.msg:
                logger.warning(
                    "Could not join user %s to space %s (maybe already joined?): %s",
                    user_id, space_id, e
                )

        # <<< ИЗМЕНЕНИЕ: Используем правильный контроллер для получения состояния >>>
        current_event = await self._state_controller.get_current_state_event(
            space_id, SUBSCRIBER_ADMIN_EVENT_TYPE, ""
        )

        current_admins = []
        if current_event and "users" in current_event.content:
            current_admins = current_event.content.get("users", [])

        if user_id not in current_admins:
            new_admins = current_admins + [user_id]
            new_content = {"users": new_admins}

            await self.event_creation_handler.create_and_send_nonmember_event(
                admin_requester,  # <<< ИЗМЕНЕНИЕ: Используем admin_requester
                {
                    "type": SUBSCRIBER_ADMIN_EVENT_TYPE,
                    "state_key": "",
                    "room_id": space_id,
                    "sender": admin_requester.user.to_string(),
                    "content": new_content,
                },
                ratelimit=False
            )
            logger.info("User %s added as subscriber admin to space %s by %s",
                        user_id, space_id, requester.user)

        return {"added_user": user_id, "space_id": space_id}


class SpaceSubscriberAdminRestServlet(RestServlet):
    """
    REST эндпоинт для API /_synapse/admin/v2/spaces/{space_id}/subscriber_admins
    Принимает POST запросы для добавления "Абонента Администратора".
    """
    # Используем /v2/, т.к. /v1/ - legacy
    PATTERNS = admin_patterns("/spaces/(?P<space_id>[^/]*)/subscriber_admins", "v2")

    def __init__(self, hs: "HomeServer"):
        super().__init__()
        self.hs = hs
        self.auth = hs.get_auth()
        self.handler = SpaceSubscriberAdminHandler(hs)

    async def on_POST(self, request: "SynapseRequest", space_id: str) -> Tuple[
        int, JsonMapping]:
        requester = await self.auth.get_user_by_req(request)

        # <<< ИЗМЕНЕНИЕ: Исправлен вызов is_server_admin >>>
        is_admin = await self.auth.is_server_admin(requester)
        if not is_admin:
            raise AuthError(403, "You must be a server admin to use this endpoint")

        body = parse_json_object_from_request(request)
        user_id = body.get("user_id")

        if not user_id:
            raise SynapseError(400, "Missing 'user_id' in request body",
                               Codes.MISSING_PARAM)

        result = await self.handler.add_subscriber_admin(space_id, user_id, requester)
        return 200, result


def register_servlets(hs: "HomeServer", http_server: HttpServer) -> None:
    """Регистрирует сервлеты из этого файла."""
    SpaceSubscriberAdminRestServlet(hs).register(http_server)