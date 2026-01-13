"""Platform for mcp23017-based switch."""

import asyncio
import functools
import logging

import voluptuous as vol

from . import async_get_or_create, setup_entry_status
from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.device_registry import DeviceInfo
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
    DEFAULT_I2C_ADDRESS,
    DEFAULT_I2C_BUS,
    DEFAULT_INVERT_LOGIC,
    DEFAULT_HW_SYNC,
    DEFAULT_MOMENTARY,
    DEFAULT_PULSE_TIME,
    DOMAIN,
    CONF_PER_PIN_DEVICE,
    DEFAULT_PER_PIN_DEVICE,
)

_LOGGER = logging.getLogger(__name__)

_SWITCHES_SCHEMA = vol.Schema({cv.positive_int: cv.string})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_PINS): _SWITCHES_SCHEMA,
        vol.Optional(CONF_INVERT_LOGIC, default=DEFAULT_INVERT_LOGIC): cv.boolean,
        vol.Optional(CONF_HW_SYNC, default=DEFAULT_HW_SYNC): cv.boolean,
        vol.Optional(CONF_I2C_ADDRESS, default=DEFAULT_I2C_ADDRESS): vol.Coerce(int),
        vol.Optional(CONF_I2C_BUS, default=DEFAULT_I2C_BUS): vol.Coerce(int),
        vol.Optional(CONF_PER_PIN_DEVICE, default=DEFAULT_PER_PIN_DEVICE): cv.boolean,
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
                    CONF_I2C_BUS: config[CONF_I2C_BUS],
                    CONF_INVERT_LOGIC: config[CONF_INVERT_LOGIC],
                    CONF_HW_SYNC: config[CONF_HW_SYNC],
                    CONF_PER_PIN_DEVICE: config[CONF_PER_PIN_DEVICE],
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
        self._turn_off_timer_cancel = None

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

        self._per_pin_device = config_entry.options.get(
            CONF_PER_PIN_DEVICE,
            config_entry.data.get(
                CONF_PER_PIN_DEVICE,
                DEFAULT_PER_PIN_DEVICE
            )
        )

        # Create or update option values for switch platform
        # Merge with existing options to avoid overwriting values from YAML import
        current_options = dict(config_entry.options)
        current_options.update({
            CONF_INVERT_LOGIC: self._invert_logic,
            CONF_HW_SYNC: self._hw_sync,
            CONF_MOMENTARY: self._momentary,
            CONF_PULSE_TIME: self._pulse_time,
            CONF_PER_PIN_DEVICE: self._per_pin_device,
        })
        hass.config_entries.async_update_entry(
            config_entry,
            options=current_options,
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
    def bus(self):
        """Return the i2c bus of the entity."""
        return self._i2c_bus

    @property
    def device_info(self):
        """Return device info for the entity."""
        per_pin_device = self._per_pin_device

        # Legacy mode: one device per MCP23017
        if not per_pin_device:
            # Use the parent MCP23017 device_info (single device for all pins)
            return self._device.device_info

        # Per-pin device mode: one device per pin
        return DeviceInfo(
            identifiers={self._device.get_pin_device_identifiers(self._pin_number)},
            name=f"{self._device.unique_id} - Pin {self._pin_number}",
            manufacturer="Microchip",
            model="MCP23017 Pin",
            via_device=(DOMAIN, self._i2c_bus, self._i2c_address),
        )


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

        if self._momentary:
            if self._turn_off_timer_cancel:
                self._turn_off_timer_cancel()

            async def turn_off_listener(now):
                await self.async_turn_off()

            self._turn_off_timer_cancel = async_call_later(
                self.hass,
                self._pulse_time / 1000.0,
                turn_off_listener
            )

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        await self.hass.async_add_executor_job(
            functools.partial(
                self._device.set_pin_value, self._pin_number, self._invert_logic
            )
        )
        self._state = False
        self.schedule_update_ha_state()

        if self._momentary:
            if self._turn_off_timer_cancel:
                self._turn_off_timer_cancel()
                self._turn_off_timer_cancel = None

    @callback
    async def async_config_update(self, hass, config_entry):
        """Handle update from config entry options."""
        self._invert_logic = config_entry.options[CONF_INVERT_LOGIC]
        self._momentary = config_entry.options[CONF_MOMENTARY]
        self._pulse_time = config_entry.options[CONF_PULSE_TIME]
        self._per_pin_device = config_entry.options.get(
            CONF_PER_PIN_DEVICE,
            DEFAULT_PER_PIN_DEVICE
        )
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
