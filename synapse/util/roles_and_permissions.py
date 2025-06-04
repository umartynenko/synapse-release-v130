import logging
from typing import Dict


logger = logging.getLogger(__name__)


async def get_user_role(hs, user_id: str) -> str:
    """Obtains custom user role from module role store """
    try:
        # logging the module availability check in detail
        if hasattr(hs, 'role_module'):
            logger.info("RoleModule found in self.hs for user: %s", user_id)
            if hasattr(hs.role_module, 'store'):
                logger.info("RoleStore found in RoleModule for user: %s", user_id)
                role_store = hs.role_module.store
                role = await role_store.get_user_role(user_id)
                logger.info("Retrieved role for %s: %s", user_id, role)
                return role
            else:
                logger.warning("RoleModule has no 'store' attribute for user: %s",
                               user_id)
        else:
            logger.warning("No RoleModule found in self.hs for user: %s", user_id)
        return "unknown"
    except Exception as e:
        logger.error("Error getting user role for %s: %s", user_id, e,
                     exc_info=True)
        return "error"


async def get_user_permissions(hs, user_id: str) -> Dict[str, bool]:
    """Obtains user permissions from module role store"""
    try:
        if hasattr(hs, 'role_module') and hasattr(hs.role_module, 'store'):
            role_store = hs.role_module.store
            return await role_store.get_user_permissions(user_id)

        # Return the default permissions if the module is unavailable
        logger.warning("RoleModule not available, using default permissions")
        return {
            "change_displayname": True,
            "change_avatar": True,
            # Other default permissions
        }
    except Exception as e:
        logger.error("Error getting user permissions: %s", e, exc_info=True)
        return {
            "change_displayname": True,
            "change_avatar": True,
        }  # Permissions by default in case of an error
