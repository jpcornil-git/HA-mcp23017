"""Platform for mcp23017-based switch."""

import asyncio
import functools
import logging

import voluptuous as vol

from . import async_get_or_create, setup_entry_status
from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_FLOW_PIN_NAME,
    CONF_FLOW_PIN_NUMBER,
    CONF_FLOW_PLATFORM,
    CONF_I2C_ADDRESS,
    CONF_I2C_BUS,
    CONF_INVERT_LOGIC,
    CONF_HW_SYNC,
    CONF_PINS,
    CONF_MOMENTARY,
    CONF_PULSE_TIME,
    CONF_PIN_NAME,
    DEFAULT_I2C_ADDRESS,
    DEFAULT_I2C_BUS,
    DEFAULT_INVERT_LOGIC,
    DEFAULT_HW_SYNC,
    DEFAULT_MOMENTARY,
    DEFAULT_PULSE_TIME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Schema for simple pin configuration (e.g., "0: setBi16")
_SIMPLE_PIN_SCHEMA = cv.string

# Schema for advanced pin configuration (e.g., "1: {name: lt_ogrod_kinkiet_taras, ...}")
_ADVANCED_PIN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PIN_NAME): cv.string,
        vol.Optional(CONF_MOMENTARY, default=DEFAULT_MOMENTARY): cv.boolean,
        vol.Optional(CONF_PULSE_TIME, default=DEFAULT_PULSE_TIME): cv.positive_int,
    }
)

# Combine simple and advanced pin schemas
_PIN_SCHEMA = vol.Any(_SIMPLE_PIN_SCHEMA, _ADVANCED_PIN_SCHEMA)

# Schema for the entire pins dictionary
_PINS_SCHEMA = vol.Schema({cv.positive_int: _PIN_SCHEMA})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_PINS): _PINS_SCHEMA,
        vol.Optional(CONF_INVERT_LOGIC, default=DEFAULT_INVERT_LOGIC): cv.boolean,
        vol.Optional(CONF_HW_SYNC, default=DEFAULT_HW_SYNC): cv.boolean,
        vol.Optional(CONF_I2C_ADDRESS, default=DEFAULT_I2C_ADDRESS): vol.Coerce(int),
        vol.Optional(CONF_I2C_BUS, default=DEFAULT_I2C_BUS): vol.Coerce(int),
    }
)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the MCP23017 for switch entities."""

    # Wait for configflow to terminate before processing configuration.yaml
    while setup_entry_status.busy():
        await asyncio.sleep(0)

    for pin_number, pin_config in config[CONF_PINS].items():
        if isinstance(pin_config, dict):
            # Advanced configuration
            pin_name = pin_config[CONF_PIN_NAME]
            momentary = pin_config[CONF_MOMENTARY]
            pulse_time = pin_config[CONF_PULSE_TIME]
        else:
            # Simple configuration
            pin_name = pin_config
            momentary = DEFAULT_MOMENTARY
            pulse_time = DEFAULT_PULSE_TIME

        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={
                    CONF_FLOW_PLATFORM: "switch",
                    CONF_FLOW_PIN_NUMBER: pin_number,
                    CONF_FLOW_PIN_NAME: pin_name,
                    CONF_I2C_ADDRESS: config[CONF_I2C_ADDRESS],
                    CONF_I2C_BUS: config[CONF_I2C_BUS],
                    CONF_INVERT_LOGIC: config[CONF_INVERT_LOGIC],
                    CONF_HW_SYNC: config[CONF_HW_SYNC],
                    CONF_MOMENTARY: momentary,
                    CONF_PULSE_TIME: pulse_time,
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


class MCP23017Switch(SwitchEntity):
    """Represent a switch that uses MCP23017."""

    def __init__(self, hass, config_entry):
        """Initialize the MCP23017 switch."""
        self._device = None
        self._state = None
        self._unsub_turn_off = None

        self._i2c_address = config_entry.data[CONF_I2C_ADDRESS]
        self._i2c_bus = config_entry.data[CONF_I2C_BUS]
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
        self._momentary = config_entry.options.get(
            CONF_MOMENTARY,
            config_entry.data.get(
                CONF_MOMENTARY,
                DEFAULT_MOMENTARY
            )
        )
        self._pulse_time = config_entry.options.get(
            CONF_PULSE_TIME,
            config_entry.data.get(
                CONF_PULSE_TIME,
                DEFAULT_PULSE_TIME
            )
        )

        # Create or update option values for switch platform
        hass.config_entries.async_update_entry(
            config_entry,
            options={
                CONF_INVERT_LOGIC: self._invert_logic,
                CONF_HW_SYNC: self._hw_sync,
                CONF_MOMENTARY: self._momentary,
                CONF_PULSE_TIME: self._pulse_time,
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
        return "mdi:toggle-switch"

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
    def bus(self):
        """Return the i2c bus of the entity."""
        return self._i2c_bus

    @property
    def device_info(self):
        """Device info."""
        return {
            "identifiers": {(DOMAIN, self._i2c_bus, self._i2c_address)},
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

    async def _async_set_pin_value(self, value):
        """
        Set the pin value and update the state.
        :param value: Desired logical state (True for on, False for off).
        """
        try:
            # Apply invert_logic to the value before setting the pin
            pin_value = not value if self._invert_logic else value
            await self.hass.async_add_executor_job(
                functools.partial(self._device.set_pin_value, self._pin_number, pin_value)
            )
            self._state = value
            self.async_write_ha_state()
            _LOGGER.debug(f"{self._pin_name} set to {value} (invert_logic: {self._invert_logic}).")
        except Exception as e:
            _LOGGER.error(f"Failed to set {self._pin_name} to {value}: {e}")

    async def _async_handle_turn_off(self, _):
        """Callback to turn off the switch after the pulse time."""
        await self._async_set_pin_value(False)
        self._unsub_turn_off = None 

    async def _async_schedule_turn_off(self):
        """Schedule the turn-off callback after the pulse time."""
        self._unsub_turn_off = async_call_later(
            self.hass,
            self._pulse_time / 1000.0,  # Convert milliseconds to seconds
            self._async_handle_turn_off  # Callback to turn off the switch
        )
        _LOGGER.debug(f"{self._pin_name} scheduled to turn off in {self._pulse_time} ms.")
        
    async def _async_cancel_turn_off_callback_if_exists(self):
        """Cancel any scheduled turn-off callback."""
        if self._unsub_turn_off:
            self._unsub_turn_off()
            self._unsub_turn_off = None
            _LOGGER.debug(f"{self._pin_name} turn-off callback cancelled.")

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        if self.is_on and not self._momentary:
            _LOGGER.debug(f"{self._pin_name} is already on. Skipping.")
            return

        await self._async_set_pin_value(True)

        if self._momentary:
            await self._async_cancel_turn_off_callback_if_exists()
            await self._async_schedule_turn_off()

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        if not self.is_on:
            _LOGGER.debug(f"{self._pin_name} is already off. Skipping.")
            return

        if self._momentary:
            await self._async_cancel_turn_off_callback_if_exists()
       
        await self._async_set_pin_value(False)  

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
