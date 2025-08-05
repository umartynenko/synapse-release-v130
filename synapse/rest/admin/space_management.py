# synapse/rest/admin/space_management.py

import logging
from typing import TYPE_CHECKING, Tuple, Optional, Dict, Any

from synapse.api.constants import Membership
from synapse.api.errors import AuthError, Codes, SynapseError, NotFoundError
from synapse.http.server import HttpServer
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.http.site import SynapseRequest
from synapse.rest.admin._base import admin_patterns
from synapse.types import JsonMapping, Requester, UserID, create_requester

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)

SUBSCRIBER_ADMIN_EVENT_TYPE = "dev.martynenko.space.subscriber_admins"
PARENT_SPACE_EVENT_TYPE = "dev.martynenko.parent_space"
SUBSCRIBER_ADMIN_LEVEL = 50


class SpaceSubscriberAdminHandler:
    def __init__(self, hs: "HomeServer"):
        self.hs = hs
        self.auth = hs.get_auth()
        self.event_creation_handler = hs.get_event_creation_handler()
        self.room_member_handler = hs.get_room_member_handler()
        self.store = hs.get_datastores().main
        self.state_store = hs.get_storage_controllers().state

    async def _find_public_chat_in_space(self, space_id: str) -> Optional[str]:
        """
        Находит ID "родного" Общего Чата (ОЧ) для данного пространства
        по кастомной метке.
        """
        logger.info(
            f"Ищем ОЧ для пространства {space_id} по метке {PARENT_SPACE_EVENT_TYPE}")
        current_state_ids = await self.state_store.get_current_state_ids(
            room_id=space_id)
        current_state_events = await self.store.get_events(current_state_ids.values())
        child_events = [
            event for event in current_state_events.values()
            if event.type == "m.space.child" and event.state_key
        ]
        for event in child_events:
            child_room_id = event.state_key
            try:
                create_event = await self.store.get_create_event_for_room(child_room_id)
                if create_event.content.get("custom.chat_type") != "public_chat":
                    continue

                parent_space_event = await self.state_store.get_current_state_event(
                    child_room_id, PARENT_SPACE_EVENT_TYPE, ""
                )
                if parent_space_event and parent_space_event.content.get(
                    "space_id") == space_id:
                    logger.info(
                        f"Найден 'родной' ОЧ: {child_room_id} для пространства {space_id}")
                    return child_room_id
            except Exception as e:
                logger.warning(
                    f"Ошибка при проверке дочерней комнаты {child_room_id}: {e}")
        logger.warning(f"'Родной' ОЧ для пространства {space_id} не найден.")
        return None

    async def add_subscriber_admin(
        self, space_id: str, user_id: str, requester: "Requester"
    ) -> Dict[str, Any]:
        """
        Полный процесс добавления "Абонента Администратора" с отключением
        автоматического присоединения к родительским пространствам.
        """
        if not await self.auth.is_server_admin(requester):
            raise AuthError(403, "You must be a server admin to use this endpoint")
        target_user = UserID.from_string(user_id)
        admin_requester = create_requester(
            requester.user, authenticated_entity=requester.user.to_string()
        )

        # Шаг 1: "Невидимые" операции с правами.
        current_power_levels_event = await self.state_store.get_current_state_event(
            space_id, "m.room.power_levels", ""
        )
        if current_power_levels_event:
            new_power_levels = dict(current_power_levels_event.content)
        else:
            new_power_levels = {"users": {}, "events": {}}
        new_power_levels.setdefault("users", {});
        new_power_levels.setdefault("events", {})
        new_power_levels["users"][user_id] = SUBSCRIBER_ADMIN_LEVEL
        new_power_levels["events"].setdefault("m.space.child", SUBSCRIBER_ADMIN_LEVEL)
        new_power_levels["events"].setdefault("invite", SUBSCRIBER_ADMIN_LEVEL)
        await self.event_creation_handler.create_and_send_nonmember_event(
            admin_requester,
            {"type": "m.room.power_levels", "state_key": "", "room_id": space_id,
             "sender": admin_requester.user.to_string(), "content": new_power_levels},
            ratelimit=False,
        )
        logger.info(f"Power levels в {space_id} обновлены для {user_id}")

        current_subscriber_admins_event = await self.state_store.get_current_state_event(
            space_id, SUBSCRIBER_ADMIN_EVENT_TYPE, ""
        )
        current_admins = current_subscriber_admins_event.content.get("users",
                                                                     []) if current_subscriber_admins_event else []
        if user_id not in current_admins:
            new_admins = current_admins + [user_id]
            await self.event_creation_handler.create_and_send_nonmember_event(
                admin_requester,
                {"type": SUBSCRIBER_ADMIN_EVENT_TYPE, "state_key": "",
                 "room_id": space_id, "sender": admin_requester.user.to_string(),
                 "content": {"users": new_admins}},
                ratelimit=False,
            )
            logger.info(f"Пользователь {user_id} добавлен в список subscriber_admins")

        # Шаг 2: СНАЧАЛА приглашаем в "родной" дочерний чат.
        public_chat_id = await self._find_public_chat_in_space(space_id)
        if public_chat_id:
            try:
                await self.room_member_handler.update_membership(
                    requester=admin_requester, target=target_user,
                    room_id=public_chat_id,
                    action=Membership.INVITE, ratelimit=False, require_consent=False,
                )
                logger.info(f"Пользователь {user_id} приглашен в ОЧ {public_chat_id}")
            except Exception:
                logger.exception(
                    f"Не удалось пригласить {user_id} в ОЧ {public_chat_id}")
        else:
            logger.warning(
                f"ОЧ для пространства {space_id} не найден, пропуск приглашения в чат.")

        # Шаг 3: В ПОСЛЕДНЮЮ ОЧЕРЕДЬ присоединяем к самому пространству, передавая флаг.
        content_controlled_join = {"dev.martynenko.controlled_join": True}
        try:
            await self.room_member_handler.update_membership(
                requester=admin_requester, target=target_user, room_id=space_id,
                action=Membership.INVITE, ratelimit=False, require_consent=False,
            )
            logger.info(f"Пользователь {user_id} приглашен в пространство {space_id}")

            target_requester = create_requester(target_user,
                                                authenticated_entity=admin_requester.user.to_string())
            await self.room_member_handler.update_membership(
                requester=target_requester, target=target_user, room_id=space_id,
                action=Membership.JOIN, ratelimit=False, require_consent=False,
                content=content_controlled_join,
            )
            logger.info(
                f"Пользователь {user_id} присоединен к пространству {space_id} (контролируемое присоединение)")
        except Exception:
            logger.exception(f"Ошибка при присоединении {user_id} к {space_id}")

        return {
            "status": "success", "user_id": user_id, "space_id": space_id,
            "invited_to_public_chat": public_chat_id,
        }


class SpaceSubscriberAdminRestServlet(RestServlet):
    PATTERNS = admin_patterns("/spaces/(?P<space_id>[^/]*)/subscriber_admins", "v2")

    def __init__(self, hs: "HomeServer"):
        super().__init__()
        self.handler = SpaceSubscriberAdminHandler(hs)

    async def on_POST(self, request: "SynapseRequest", space_id: str) -> Tuple[
        int, JsonMapping]:
        requester = await self.handler.auth.get_user_by_req(request)
        body = parse_json_object_from_request(request)
        user_id = body.get("user_id")
        if not user_id:
            raise SynapseError(400, "Missing 'user_id' in request body",
                               Codes.MISSING_PARAM)
        result = await self.handler.add_subscriber_admin(space_id, user_id, requester)
        return 200, result


def register_servlets(hs: "HomeServer", http_server: HttpServer) -> None:
    SpaceSubscriberAdminRestServlet(hs).register(http_server)