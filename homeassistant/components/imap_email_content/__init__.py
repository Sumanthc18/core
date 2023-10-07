"""The imap_email_content component."""

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.deprecated(DOMAIN, raise_if_present=False)


async def async_setup() -> bool:
    """Set up imap_email_content."""
    return True
