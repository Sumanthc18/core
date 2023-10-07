"""The Screenlogic integration."""
import logging
from typing import Any

from screenlogicpy import ScreenLogicError, ScreenLogicGateway
from screenlogicpy.const.data import SHARED_VALUES

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import ScreenlogicDataUpdateCoordinator, async_get_connect_info
from .data import ENTITY_MIGRATIONS
from .services import async_load_screenlogic_services, async_unload_screenlogic_services
from .util import generate_unique_id

_LOGGER = logging.getLogger(__name__)

REQUEST_REFRESH_DELAY = 2
HEATER_COOLDOWN_DELAY = 6

# These seem to be constant across all controller models
PRIMARY_CIRCUIT_IDS = [500, 505]  # [Spa, Pool]

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Screenlogic from a config entry."""

    await _async_migrate_entries(hass, entry)

    gateway = ScreenLogicGateway()

    connect_info = await async_get_connect_info(hass, entry)

    try:
        await gateway.async_connect(**connect_info)
        await gateway.async_update()
    except ScreenLogicError as ex:
        raise ConfigEntryNotReady(ex.msg) from ex

    coordinator = ScreenlogicDataUpdateCoordinator(
        hass, config_entry=entry, gateway=gateway
    )

    async_load_screenlogic_services(hass)

    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.gateway.async_disconnect()
        hass.data[DOMAIN].pop(entry.entry_id)

    async_unload_screenlogic_services(hass)

    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_migrate_entries(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Migrate to new entity names."""
    entity_registry = er.async_get(hass)

    for entry in er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    ):
        source_mac, source_key, source_index = get_source_info(entry.unique_id)

        if source_key not in ENTITY_MIGRATIONS:
            continue

        migrations = ENTITY_MIGRATIONS[source_key]
        updates = {}

        new_key = migrations["new_key"]
        new_unique_id = generate_new_unique_id(
            source_mac, source_index, new_key, entry, migrations
        )

        if should_migrate_unique_id(entry, new_unique_id, entity_registry):
            updates["new_unique_id"] = new_unique_id

        update_entity_names(entry, migrations)

        if updates:
            update_entity(entry, updates, entity_registry)


def get_source_info(unique_id):
    source_mac, source_key = unique_id.split("_", 1)
    source_index = get_source_index(source_key)
    return source_mac, source_key, source_index


def get_source_index(source_key):
    source_index = None
    if (
        len(key_parts := source_key.rsplit("_", 1)) == 2
        and key_parts[1].isdecimal()
    ):
        source_key, source_index = key_parts
    return source_index


def should_migrate_unique_id(entry, new_unique_id, entity_registry):
    if new_unique_id and new_unique_id != entry.unique_id:
        existing_entity_id = entity_registry.async_get_entity_id(
            entry.domain, entry.platform, new_unique_id
        )
        if not existing_entity_id:
            return True
    return False


def update_entity_names(entry, migrations):
    old_name = migrations.get("old_name")

    if old_name:
        new_name = migrations["new_name"]
        if old_name_in_entity_id(entry, old_name):
            new_entity_id = entry.entity_id.replace(
                slugify(old_name), slugify(new_name)
            )
            if new_entity_id and new_entity_id != entry.entity_id:
                updates["new_entity_id"] = new_entity_id

        if old_name_in_original_name(entry, old_name):
            new_original_name = entry.original_name.replace(old_name, new_name)
            if new_original_name and new_original_name != entry.original_name:
                updates["original_name"] = new_original_name


def old_name_in_entity_id(entry, old_name):
    return slugify(old_name) in entry.entity_id


def old_name_in_original_name(entry, old_name):
    return entry.original_name and old_name in entry.original_name


def update_entity(entry, updates, entity_registry):
    _LOGGER.debug(
        "Migrating entity '%s' unique_id from '%s' to '%s'",
        entry.entity_id,
        entry.unique_id,
        updates["new_unique_id"],
    )
    entity_registry.async_update_entity(entry.entity_id, **updates)
