"""Platform for mcp23017-based switch."""

import asyncio
import functools
import logging

import voluptuous as vol

from . import async_get_or_create, setup_entry_status
from homeassistant.components.switch import PLATFORM_SCHEMA, ToggleEntity
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_FLOW_PIN_NAME,
    CONF_FLOW_PIN_NUMBER,
    CONF_FLOW_PLATFORM,
    CONF_I2C_ADDRESS,
    CONF_INVERT_LOGIC,
    CONF_HW_SYNC,
    CONF_PINS,
    DEFAULT_I2C_ADDRESS,
    DEFAULT_INVERT_LOGIC,
    DEFAULT_HW_SYNC,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_SWITCHES_SCHEMA = vol.Schema({cv.positive_int: cv.string})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_PINS): _SWITCHES_SCHEMA,
        vol.Optional(CONF_INVERT_LOGIC, default=DEFAULT_INVERT_LOGIC): cv.boolean,
        vol.Optional(CONF_HW_SYNC, default=DEFAULT_HW_SYNC): cv.boolean,
        vol.Optional(CONF_I2C_ADDRESS, default=DEFAULT_I2C_ADDRESS): vol.Coerce(int),
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the MCP23017 for switch entities."""

    # Wait for configflow to terminate before processing configuration.yaml
    while setup_entry_status.busy():
        await asyncio.sleep(0)

    for pin_number, pin_name in config[CONF_PINS].items():
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={
                    CONF_FLOW_PLATFORM: "switch",
                    CONF_FLOW_PIN_NUMBER: pin_number,
                    CONF_FLOW_PIN_NAME: pin_name,
                    CONF_I2C_ADDRESS: config[CONF_I2C_ADDRESS],
                    CONF_INVERT_LOGIC: config[CONF_INVERT_LOGIC],
                    CONF_HW_SYNC: config[CONF_HW_SYNC],
                },
            )
        )


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up a MCP23017 switch entry."""

    switch_entity = MCP23017Switch(hass, config_entry)
    switch_entity.device = await async_get_or_create(
        hass, config_entry, switch_entity
    )

    if await hass.async_add_executor_job(switch_entity.configure_device):
        async_add_entities([switch_entity])


async def async_unload_entry(hass, config_entry):
    """Unload MCP23017 switch entry corresponding to config_entry."""
    _LOGGER.warning("[FIXME] async_unload_entry not implemented")


class MCP23017Switch(ToggleEntity):
    """Represent a switch that uses MCP23017."""

    def __init__(self, hass, config_entry):
        """Initialize the MCP23017 switch."""
        self._device = None
        self._state = None

        self._i2c_address = config_entry.data[CONF_I2C_ADDRESS]
        self._pin_name = config_entry.data[CONF_FLOW_PIN_NAME]
        self._pin_number = config_entry.data[CONF_FLOW_PIN_NUMBER]

        # Get invert_logic from config flow (options) or import (data)
        self._invert_logic = config_entry.options.get(
            CONF_INVERT_LOGIC,
            config_entry.data.get(
                CONF_INVERT_LOGIC,
                DEFAULT_INVERT_LOGIC
            )
        )

        # Get hw_sync from config flow (options) or import (data)
        self._hw_sync = config_entry.options.get(
            CONF_HW_SYNC,
            config_entry.data.get(
                CONF_HW_SYNC,
                DEFAULT_HW_SYNC
            )
        )

        # Create or update option values for switch platform
        hass.config_entries.async_update_entry(
            config_entry,
            options={
                CONF_INVERT_LOGIC: self._invert_logic,
                CONF_HW_SYNC: self._hw_sync,
            },
        )

        # Subscribe to updates of config entry options
        self._unsubscribe_update_listener = config_entry.add_update_listener(
            self.async_config_update
        )

        _LOGGER.info(
            "%s(pin %d:'%s') created",
            type(self).__name__,
            self._pin_number,
            self._pin_name,
        )

    @property
    def icon(self):
        """Return device icon for this entity."""
        return "mdi:chip"

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._device.unique_id}-0x{self._pin_number:02x}"

    @property
    def name(self):
        """Return the name of the switch."""
        return self._pin_name

    @property
    def is_on(self):
        """Return true if device is on."""
        return self._state

    @property
    def pin(self):
        """Return the pin number of the entity."""
        return self._pin_number

    @property
    def address(self):
        """Return the i2c address of the entity."""
        return self._i2c_address

    @property
    def device_info(self):
        """Device info."""
        return {
            "identifiers": {(DOMAIN, self._i2c_address)},
            "manufacturer": "Microchip",
            "model": "MCP23017",
            "entry_type": DeviceEntryType.SERVICE,
        }

    @property
    def device(self):
        """Get device property."""
        return self._device

    @device.setter
    def device(self, value):
        """Set device property."""
        self._device = value

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        await self.hass.async_add_executor_job(
            functools.partial(
                self._device.set_pin_value, self._pin_number, not self._invert_logic
            )
        )
        self._state = True
        self.schedule_update_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        await self.hass.async_add_executor_job(
            functools.partial(
                self._device.set_pin_value, self._pin_number, self._invert_logic
            )
        )
        self._state = False
        self.schedule_update_ha_state()

    @callback
    async def async_config_update(self, hass, config_entry):
        """Handle update from config entry options."""
        self._invert_logic = config_entry.options[CONF_INVERT_LOGIC]
        await hass.async_add_executor_job(
            functools.partial(
                self._device.set_pin_value,
                self._pin_number,
                self._state ^ self._invert_logic,
            )
        )
        self.async_schedule_update_ha_state()

    def unsubscribe_update_listener(self):
        """Remove listener from config entry options."""
        self._unsubscribe_update_listener()

    # Sync functions executed outside of hass async loop.

    def configure_device(self):
        """Attach instance to a device on the given address and configure it.

        This function should be called from the thread pool as it contains blocking functions.

        Return True when successful.
        """
        if self.device:
            # Reset pin value when HW sync is not required
            if not self._hw_sync:
                self._device.set_pin_value(self._pin_number, self._invert_logic)
            # Configure entity as output for a switch
            self._device.set_input(self._pin_number, False)
            self._state = self._device.get_pin_value(self._pin_number) ^ self._invert_logic

            return True

        return False
