"""Support for I2C MCP23017 chip."""

import asyncio
import functools
import logging
import threading
import time

import smbus2

from homeassistant.const import EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.helpers import device_registry
from homeassistant.helpers.entity_registry import async_migrate_entries
from homeassistant.components import persistent_notification

from .const import (
    CONF_FLOW_PIN_NUMBER,
    CONF_FLOW_PLATFORM,
    CONF_I2C_ADDRESS,
    CONF_I2C_BUS,
    DEFAULT_I2C_BUS,
    DEFAULT_SCAN_RATE,
    DOMAIN,
)

# MCP23017 Register Map (IOCON.BANK = 1, MCP23008-compatible)
IODIRA = 0x00
IODIRB = 0x10
IPOLA = 0x01
IPOLB = 0x11
GPINTENA = 0x02
GPINTENB = 0x12
DEFVALA = 0x03
DEFVALB = 0x13
INTCONA = 0x04
INTCONB = 0x14
IOCONA = 0x05
IOCONB = 0x15
GPPUA = 0x06
GPPUB = 0x16
INTFA = 0x07
INTFB = 0x17
INTCAPA = 0x08
INTCAPB = 0x18
GPIOA = 0x09
GPIOB = 0x19
OLATA = 0x0a
OLATB = 0x1a

# Register address used to toggle IOCON.BANK to 1 (only mapped when BANK is 0)
IOCON_REMAP = 0x0b

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "switch"]

MCP23017_DATA_LOCK = asyncio.Lock()

class SetupEntryStatus:
    """Class registering the number of outstanding async_setup_entry calls."""
    def __init__(self):
        """Initialize call counter."""
        self.number = 0
    def __enter__(self):
        """Increment call counter (with statement)."""
        self.number +=1
    def __exit__(self, exc_type, exc_value, exc_tb):
        """Decrement call counter (with statement)."""
        self.number -=1
    def busy(self):
        """Return True when there is at least one outstanding call"""
        return self.number != 0

setup_entry_status = SetupEntryStatus()


async def async_migrate_entry(hass, config_entry):
    """Migrate old config_entry and associated entities/devices."""
    _LOGGER.info("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        # Migrate config_entry
        data = {**config_entry.data}
        data[CONF_I2C_BUS] = DEFAULT_I2C_BUS
        hass.config_entries.async_update_entry(
            config_entry,
            version=2,
            data=data,
            unique_id= config_entry.unique_id.replace(f"{DOMAIN}.", f"{DOMAIN}.{DEFAULT_I2C_BUS}."),
            title = f"Bus: {DEFAULT_I2C_BUS:d}, address: {config_entry.title}"
        )

        # Migrate device
        dev_reg = device_registry.async_get(hass)
        for device_id, device in dev_reg.devices.items():
            new_identifiers={(DOMAIN, DEFAULT_I2C_BUS, data[CONF_I2C_ADDRESS])}
            if (config_entry.entry_id in device.config_entries) and (device.identifiers != new_identifiers):
                dev_reg.async_update_device(
                    device_id,
                    new_identifiers=new_identifiers
                )

        # Migrate entities
        @callback
        def _update_unique_id(entity_entry):
            # Update parent device
            return {"new_unique_id": entity_entry.unique_id.replace(f"{DOMAIN}-", f"{DOMAIN}:{DEFAULT_I2C_BUS}:")}

        await async_migrate_entries(hass, config_entry.entry_id, _update_unique_id)

        _LOGGER.info("Migration to version %s successful", config_entry.version)
        return True

    _LOGGER.warning("Migration from version %s not supported", config_entry.version)
    return False


async def async_setup(hass, config):
    """Set up the component."""

    # hass.data[DOMAIN] stores one entry for each MCP23017 instance using i2c address as a key
    hass.data.setdefault(DOMAIN, {})

    # Callback function to start polling when HA starts
    def start_polling(event):
        for component in hass.data[DOMAIN].values():
            if not component.is_alive():
                component.start_polling()

    # Callback function to stop polling when HA stops
    def stop_polling(event):
        for component in hass.data[DOMAIN].values():
            if component.is_alive():
                component.stop_polling()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, start_polling)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_polling)

    return True


async def async_setup_entry(hass, config_entry):
    """Set up the MCP23017 from a config entry."""

    # Register this setup instance
    with setup_entry_status:
        # Forward entry setup to configured platform
        await hass.config_entries.async_forward_entry_setups(
            config_entry, [config_entry.data[CONF_FLOW_PLATFORM]]
        )

    return True


async def async_unload_entry(hass, config_entry):
    """Unload entity from MCP23017 component and platform."""
    # Unload related platform
    await hass.config_entries.async_forward_entry_unload(
        config_entry, config_entry.data[CONF_FLOW_PLATFORM]
    )

    i2c_address = config_entry.data[CONF_I2C_ADDRESS]
    i2c_bus = config_entry.data[CONF_I2C_BUS]
    domain_id = MCP23017.domain_id(i2c_bus, i2c_address)

    # DOMAIN data async mutex
    async with MCP23017_DATA_LOCK:
        if domain_id in hass.data[DOMAIN]:
            component = hass.data[DOMAIN][domain_id]

            # Unlink entity from component
            await hass.async_add_executor_job(
                functools.partial(
                    component.unregister_entity, config_entry.data[CONF_FLOW_PIN_NUMBER]
                )
            )

            # Free component if not linked to any entities
            if component.has_no_entities:
                if component.is_alive():
                    await hass.async_add_executor_job(component.stop_polling)
                hass.data[DOMAIN].pop(domain_id)

                _LOGGER.info("%s component destroyed", component.unique_id)
        else:
            _LOGGER.warning(
                "%s:%s component not found, unable to unload entity.",
                DOMAIN,
                domain_id,
            )

    return True


async def async_get_or_create(hass, config_entry, entity):
    """Get or create a MCP23017 component from entity i2c address."""

    i2c_address = entity.address
    i2c_bus = entity.bus
    domain_id = MCP23017.domain_id(i2c_bus, i2c_address)

    # DOMAIN data async mutex
    try:
        async with MCP23017_DATA_LOCK:
            if domain_id in hass.data[DOMAIN]:
                component = hass.data[DOMAIN][domain_id]
            else:
                # Try to create component when it doesn't exist
                component = await hass.async_add_executor_job(
                    functools.partial(MCP23017, i2c_bus, i2c_address)
                )
                hass.data[DOMAIN][domain_id] = component

                # Start polling thread if hass is already running
                if hass.is_running:
                    component.start_polling()

                # Register a device combining all related entities
                devices = device_registry.async_get(hass)
                devices.async_get_or_create(
                    config_entry_id=config_entry.entry_id,
                    identifiers={(DOMAIN, i2c_bus, i2c_address)},
                    manufacturer="MicroChip",
                    model=DOMAIN,
                    name=component.unique_id,
                )

            # Link entity to component
            await hass.async_add_executor_job(
                functools.partial(component.register_entity, entity)
            )

    except ValueError as error:
        component = None
        await hass.config_entries.async_remove(config_entry.entry_id)

        persistent_notification.create(
            hass,
            f"Error: Unable to access {DOMAIN}:{domain_id} ({error})",
            title=f"{DOMAIN} Configuration",
            notification_id=f"{DOMAIN} notification",
        )

    return component


def i2c_device_exist(bus, address):
    try:
        smbus2.SMBus(bus).read_byte(address)
    except (FileNotFoundError, OSError) as error:
        return False
    return True


class MCP23017(threading.Thread):
    """MCP23017 device driver."""

    def __init__(self, bus, address):
        """Create a MCP23017 instance at {address} on I2C {bus}."""
        self._address = address
        self._busNumber = bus
        self._i2c_faulted = False
        self._i2c_suppressed_logs = 0

        # Check device presence
        try:
            self._bus = smbus2.SMBus(self._busNumber)
            self._bus.read_byte(self._address)
        except (FileNotFoundError, OSError) as error:
            _LOGGER.error(
                "Unable to access %s (%s)",
                self.unique_id,
                error,
            )
            raise ValueError(error) from error

        # Change register map (IOCON.BANK = 1) to support/make it compatible with MCP23008
        # - Note: when BANK is already set to 1, e.g. HA restart without power cycle,
        #   IOCON_REMAP address is not mapped and write is ignored
        self[IOCON_REMAP] = self[IOCON_REMAP] | 0x80

        self._device_lock = threading.Lock()
        self._run = False
        self._cache = {
            "IODIR": (self[IODIRB] << 8) + self[IODIRA],
            "GPPU": (self[GPPUB] << 8) + self[GPPUA],
            "GPIO": (self[GPIOB] << 8) + self[GPIOA],
            "OLAT": (self[OLATB] << 8) + self[OLATA],
        }
        self._entities = [None for i in range(16)]
        self._update_bitmap = 0

        threading.Thread.__init__(self, name=self.unique_id)

        _LOGGER.info("%s device created", self.unique_id)

    def __enter__(self):
        """Lock access to device (with statement)."""
        self._device_lock.acquire()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        """Unlock access to device (with statement)."""
        self._device_lock.release()
        return False

    def __setitem__(self, register, value):
        """Set MCP23017 {register} to {value}."""
        try:
            self._bus.write_byte_data(self._address, register, value)
            if self._i2c_faulted:
                _LOGGER.info(
                    "I2C access recovered for %s (suppressed %d log(s))",
                    self.unique_id,
                    self._i2c_suppressed_logs,
                )
                self._i2c_faulted = False
                self._i2c_suppressed_logs = 0
        except (OSError) as error:
            if self._i2c_faulted:
                self._i2c_suppressed_logs += 1
            else:
                _LOGGER.error(
                    "I2C write failure %s 0x%02x[0x%02x] <- 0x%02x (%s); suppressing until recovery",
                    self.unique_id,
                    self._address,
                    register,
                    value,
                    error,
                )
                self._i2c_faulted = True
                self._i2c_suppressed_logs = 0

    def __getitem__(self, register):
        """Get value of MCP23017 {register}."""
        try:
            data = self._bus.read_byte_data(self._address, register)
            if self._i2c_faulted:
                _LOGGER.info(
                    "I2C access recovered for %s (suppressed %d log(s))",
                    self.unique_id,
                    self._i2c_suppressed_logs,
                )
                self._i2c_faulted = False
                self._i2c_suppressed_logs = 0
        except (OSError) as error:
            data = 0
            if self._i2c_faulted:
                self._i2c_suppressed_logs += 1
            else:
                _LOGGER.error(
                    "I2C read failure %s 0x%02x[0x%02x] (%s); suppressing until recovery",
                    self.unique_id,
                    self._address,
                    register,
                    error,
                )
                self._i2c_faulted = True
                self._i2c_suppressed_logs = 0
        return data

    def _get_register_value(self, register, bit):
        """Get MCP23017 {bit} of {register}."""
        if bit < 8:
            value = self[globals()[register + "A"]] & 0xFF
            self._cache[register] = self._cache[register] & 0xFF00 | value
        else:
            value = self[globals()[register + "B"]] & 0xFF
            self._cache[register] = self._cache[register] & 0x00FF | (value << 8)

        return bool(self._cache[register] & (1 << bit))

    def _set_register_value(self, register, bit, value):
        """Set MCP23017 {bit} of {register} to {value}."""
        # Update cache
        cache_old = self._cache[register]
        if value:
            self._cache[register] |= (1 << bit) & 0xFFFF
        else:
            self._cache[register] &= ~(1 << bit) & 0xFFFF
        # Update device register only if required (minimize # of I2C  transactions)
        if cache_old != self._cache[register]:
            if bit < 8:
                self[globals()[register + "A"]] = self._cache[register] & 0xFF
            else:
                self[globals()[register + "B"]] = (self._cache[register] >> 8) & 0xFF

    @property
    def address(self):
        """Return device address."""
        return self._address

    @property
    def bus(self):
        """Return device bus."""
        return self._busNumber

    @staticmethod
    def domain_id(i2c_bus, i2c_address):
        """Returns address decorated with bus"""
        return f"{i2c_bus}:0x{i2c_address:02x}"

    @property
    def unique_id(self):
        """Return component unique id."""
        return f"{DOMAIN}:{self.domain_id(self.bus, self.address)}"

    @property
    def has_no_entities(self):
        """Check if there are no more entities attached."""
        return not any(self._entities)

    # -- Called from HA thread pool

    def get_pin_value(self, pin):
        """Get MCP23017 GPIO[{pin}] value."""
        with self:
            return self._get_register_value("GPIO", pin)

    def set_pin_value(self, pin, value):
        """Set MCP23017 GPIO[{pin}] to {value}."""
        with self:
            self._set_register_value("OLAT", pin, value)

    def set_input(self, pin, is_input):
        """Set MCP23017 GPIO[{pin}] as input."""
        with self:
            self._set_register_value("IODIR", pin, is_input)

    def set_pullup(self, pin, is_pullup):
        """Set MCP23017 GPIO[{pin}] as pullup."""
        with self:
            self._set_register_value("GPPU", pin, is_pullup)

    def register_entity(self, entity):
        """Register entity to this device instance."""
        with self:
            self._entities[entity.pin] = entity

            # Trigger a callback to update initial state
            self._update_bitmap |= (1 << entity.pin) & 0xFFFF

            _LOGGER.info(
                "%s(pin %d:'%s') attached to %s",
                type(entity).__name__,
                entity.pin,
                entity.name,
                self.unique_id,
            )

        return True

    def unregister_entity(self, pin_number):
        """Unregister entity from the device."""
        with self:
            entity = self._entities[pin_number]
            entity.unsubscribe_update_listener()
            self._entities[pin_number] = None

            _LOGGER.info(
                "%s(pin %d:'%s') removed from %s",
                type(entity).__name__,
                entity.pin,
                entity.name,
                self.unique_id,
            )

    # -- Threading components

    def start_polling(self):
        """Start polling thread."""
        self._run = True
        self.start()

    def stop_polling(self):
        """Stop polling thread."""
        self._run = False
        self.join()

    def run(self):
        """Poll all ports once and call corresponding callback if a change is detected."""

        _LOGGER.info("%s start polling thread", self.unique_id)

        while self._run:
            with self:
                # Read pin values for bank A and B from device only if there are associated callbacks (minimize # of I2C  transactions)
                input_state = self._cache["GPIO"]
                if any(
                    hasattr(entity, "push_update") for entity in self._entities[0:8]
                ):
                    input_state = input_state & 0xFF00 | self[GPIOA]
                if any(
                    hasattr(entity, "push_update") for entity in self._entities[8:16]
                ):
                    input_state = input_state & 0x00FF | (self[GPIOB] << 8)

                # Check pin values that changed and update input cache
                self._update_bitmap = self._update_bitmap | (
                    input_state ^ self._cache["GPIO"]
                )
                self._cache["GPIO"] = input_state
                # Call callback functions only for pin that changed
                for pin in range(16):
                    if (self._update_bitmap & 0x1) and hasattr(
                        self._entities[pin], "push_update"
                    ):
                        self._entities[pin].push_update(bool(input_state & 0x1))
                    input_state >>= 1
                    self._update_bitmap >>= 1

            time.sleep(DEFAULT_SCAN_RATE)

        _LOGGER.info("%s stop polling thread", self.unique_id)
