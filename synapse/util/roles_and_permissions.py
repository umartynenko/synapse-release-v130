# synapse/util/roles_and_permissions.py

import logging
from typing import TYPE_CHECKING, Dict

from synapse.storage.database import DatabasePool, Connection

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class RoleHandler:
    """
    Обработчик для управления ролями пользователей и их правами,
    интегрированный в ядро Synapse. Работает напрямую с базой данных.
    """
    _TABLE_NAME = "user_roles"
    _DEFAULT_ROLE = "subscriber"

    def __init__(self, hs: "HomeServer"):
        self.hs = hs
        self.db_pool: DatabasePool = hs.get_datastores().main.db_pool
        # Регистрируем фоновое обновление для создания таблицы при запуске.
        # Это гарантирует, что таблица будет создана, если ее нет.
        self.db_pool.updates.register_background_update_handler(
            f"init_{self._TABLE_NAME}", self._init_table
        )
        logger.info("Initialized RoleHandler with table '%s'", self._TABLE_NAME)

    async def _init_table(self, progress: dict, db_conn: Connection) -> int:
        """Создает таблицу, если она не существует."""

        # run_db_interaction уже обрабатывает курсор и коммит.
        def _create_table_txn(txn: Connection) -> None:
            txn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE_NAME} (
                    user_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT '{self._DEFAULT_ROLE}' CHECK (role IN (
                        'admin', 'org_admin', 'subscriber',
                        'space_leader', 'space_admin', 'vip', 'moderator', 'user'
                    ))
                )
                """
            )

        await self.db_pool.run_db_interaction(f"create_{self._TABLE_NAME}",
                                              _create_table_txn)
        return 1

    async def get_user_role(self, user_id: str) -> str:
        """Получает роль пользователя из базы данных."""
        role = await self.db_pool.simple_select_one_onecol(
            table=self._TABLE_NAME,
            keyvalues={"user_id": user_id},
            retcol="role",
            allow_none=True,
        )

        return role or self._DEFAULT_ROLE

    async def set_user_role(self, user_id: str, role: str) -> None:
        """Устанавливает или обновляет роль пользователя."""
        await self.db_pool.simple_upsert(
            table=self._TABLE_NAME,
            keyvalues={"user_id": user_id},
            values={"role": role},
        )

    async def get_user_permissions(self, user_id: str) -> Dict[str, bool]:
        """Определяет права пользователя на основе его роли."""
        role = await self.get_user_role(user_id)

        # Копируем структуру прав из вашего `role_store.py`
        permissions = {
            # Federation management
            "create_federations": False,
            # create new federations with other organizations
            "upload_federation_users": False,  # upload usernames to federations

            # Organization administration
            "create_user_database": False,
            # create organization's user database, add users to organization

            # Space management
            "name_spaces": False,  # specify names for Spaces
            "manage_space_users": False,  # add/remove users to spaces
            "manage_space_structure": False,  # create/modify spaces structure

            # Room management
            "create_private_room": False,  # create individual room/call
            "create_room": False,  # create public room
            "delete_room": False,  # delete chats
            "modify_room_attributes": False,  # change chat attributes
            "manage_room_users": False,  # remove/add users to chats
            "delete_messages": False,  # delete messages (except self-destructing)

            # User management
            "assign_organization_admin": False,  # appoint organization administrators
            "assign_leader": False,  # appoint user as leader
            "assign_admin": False,  # appoint user as chat administrator
            "grant_chat_admin_rights": False,  # grant admin rights in chats

            # Profile management
            "change_displayname": False,  # change own display name
            "change_avatar": False,  # change own avatar and other profile details

            # Chat/space participation
            "leave_room_space": False,  # user can leave rooms and spaces

            # Search
            "search_public_chats": False,  # search public chats and users

            # Notifications
            "toggle_notifications": False,  # enable/disable chat notifications

            # VIP subscriber permission
            "block_self_chats": False  # restrict creating chat with oneself
        }

        if role == "admin":  # Администратор
            permissions.update({
                "create_room": False,
                "delete_messages": False,
                "change_avatar": False,
                "change_displayname": False,
            })
        elif role == "org_admin":  # Администратор организации
            permissions.update({
                "create_room": True,
                "delete_messages": True,
                "change_avatar": True,
                "change_displayname": True,
            })
        elif role == "space_leader":  # Абонент руководитель
            permissions.update({
                "create_room": True,
                "delete_messages": True,
                "change_avatar": True,
                "change_displayname": True,
            })
        elif role == "space_admin":  # Абонент администратор
            permissions.update({
                "create_room": True,
                "delete_messages": False,
                "change_avatar": True,
                "change_displayname": True,
            })
        elif role == "vip":  # Абонент vip
            permissions.update({
                "create_room": True,
                "delete_messages": True,
                "change_avatar": False,
                "change_displayname": False,
            })
        elif role == "moderator":
            pass
        elif role == "user":
            pass
        elif role == "subscriber":  # Абонент
            permissions.update({
                "create_room": False,
                "delete_messages": False,
                "change_avatar": False,
                "change_displayname": False,
            })

        logger.debug("Permissions for %s (role: %s): %s", user_id, role, permissions)

        return permissions
