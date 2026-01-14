"""Config flow for MCP23017 component."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from . import i2c_device_exist
from .const import (
    CONF_FLOW_PIN_NAME,
    CONF_FLOW_PIN_NUMBER,
    CONF_FLOW_PLATFORM,
    CONF_I2C_ADDRESS,
    CONF_I2C_BUS,
    CONF_INVERT_LOGIC,
    CONF_PULL_MODE,
    CONF_HW_SYNC,
    CONF_MOMENTARY,
    CONF_PULSE_TIME,
    DEFAULT_I2C_ADDRESS,
    DEFAULT_I2C_BUS,
    DEFAULT_INVERT_LOGIC,
    DEFAULT_PULL_MODE,
    DEFAULT_HW_SYNC,
    DEFAULT_MOMENTARY,
    DEFAULT_PULSE_TIME,
    DOMAIN,
    MODE_DOWN,
    MODE_UP,
    CONF_PER_PIN_DEVICE,          # ← NUEVO
    DEFAULT_PER_PIN_DEVICE,       # ← NUEVO
)

PLATFORMS = ["binary_sensor", "switch"]


class Mcp23017ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """MCP23017 config flow."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def _title(self, user_input):
        return "Bus: %d, address: 0x%02x, pin: %d ('%s':%s)" % (
            user_input[CONF_I2C_BUS],
            user_input[CONF_I2C_ADDRESS],
            user_input[CONF_FLOW_PIN_NUMBER],
            user_input[CONF_FLOW_PIN_NAME],
            user_input[CONF_FLOW_PLATFORM],
        )

    def _unique_id(self, user_input):
        return "%s.%d.%d.%d" % (
            DOMAIN,
            user_input[CONF_I2C_BUS],
            user_input[CONF_I2C_ADDRESS],
            user_input[CONF_FLOW_PIN_NUMBER],
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Add support for config flow options."""
        return Mcp23017OptionsFlowHandler()

    async def async_step_import(self, user_input=None):
        """Create a new entity from configuration.yaml import."""

        config_entry = await self.async_set_unique_id(self._unique_id(user_input))
        # Remove entry (from storage) matching the same unique id
        if config_entry:
            await self.hass.config_entries.async_remove(config_entry.entry_id)

        return self.async_create_entry(
            title=self._title(user_input),
            data=user_input,
        )

    async def async_step_user(self, user_input=None):
        """Create a new entity from UI."""

        if user_input is not None:
            # Validate and convert I2C bus, address, and pin number
            try:
                user_input[CONF_I2C_BUS] = int(user_input[CONF_I2C_BUS])
                if user_input[CONF_I2C_BUS] < 0 or user_input[CONF_I2C_BUS] > 9:
                    raise ValueError("I2C bus must be between 0 and 9")
                
                # Handle I2C address - accept both hex (0x20) and decimal (32) formats
                addr_str = user_input[CONF_I2C_ADDRESS].strip()
                if addr_str.lower().startswith("0x"):
                    user_input[CONF_I2C_ADDRESS] = int(addr_str, 16)
                else:
                    user_input[CONF_I2C_ADDRESS] = int(addr_str)
                
                if user_input[CONF_I2C_ADDRESS] < 0 or user_input[CONF_I2C_ADDRESS] > 127:
                    raise ValueError("I2C address must be between 0 (0x00) and 127 (0x7F)")
                
                user_input[CONF_FLOW_PIN_NUMBER] = int(user_input[CONF_FLOW_PIN_NUMBER])
                if user_input[CONF_FLOW_PIN_NUMBER] < 0 or user_input[CONF_FLOW_PIN_NUMBER] > 15:
                    raise ValueError("Pin number must be between 0 and 15")
            except (ValueError, TypeError) as e:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_user_schema(user_input),
                    errors={"base": str(e)},
                )
            
            await self.async_set_unique_id(self._unique_id(user_input))
            self._abort_if_unique_id_configured()

            if CONF_FLOW_PIN_NAME not in user_input:
                user_input[CONF_FLOW_PIN_NAME] = "pin %d:0x%02x:%d" % (
                    user_input[CONF_I2C_BUS],
                    user_input[CONF_I2C_ADDRESS],
                    user_input[CONF_FLOW_PIN_NUMBER],
                )

            if i2c_device_exist(user_input[CONF_I2C_BUS], user_input[CONF_I2C_ADDRESS]):
                return self.async_create_entry(
                    title=self._title(user_input),
                    data=user_input,
                )
            else:
                return self.async_abort(reason="Invalid I2C address")

        return self.async_show_form(
            step_id="user",
            data_schema=self._get_user_schema(),
        )

    def _get_user_schema(self, user_input=None):
        """Get the user input schema."""
        if user_input is None:
            user_input = {}
        
        # Format I2C address as hex if it's a number
        i2c_addr = user_input.get(CONF_I2C_ADDRESS, DEFAULT_I2C_ADDRESS)
        if isinstance(i2c_addr, int):
            i2c_addr_str = f"0x{i2c_addr:02x}"
        else:
            i2c_addr_str = str(i2c_addr)
        
        return vol.Schema(
            {
                vol.Required(
                    CONF_I2C_BUS, default=str(user_input.get(CONF_I2C_BUS, DEFAULT_I2C_BUS))
                ): str,
                vol.Required(
                    CONF_I2C_ADDRESS, default=i2c_addr_str
                ): str,
                vol.Required(
                    CONF_FLOW_PIN_NUMBER, default=str(user_input.get(CONF_FLOW_PIN_NUMBER, 0))
                ): str,
                vol.Required(
                    CONF_FLOW_PLATFORM,
                    default=user_input.get(CONF_FLOW_PLATFORM, PLATFORMS[0]),
                ): vol.In(PLATFORMS),
                vol.Optional(CONF_FLOW_PIN_NAME, default=user_input.get(CONF_FLOW_PIN_NAME, "")): str,
            }
        )

class Mcp23017OptionsFlowHandler(config_entries.OptionsFlow):
    """MCP23017 config flow options."""

    async def async_step_init(self, user_input=None):
        """Manage entity options."""

        if user_input is not None:
            # Check if per_pin_device changed
            per_pin_device_changed = user_input.get(CONF_PER_PIN_DEVICE) != self.config_entry.options.get(
                CONF_PER_PIN_DEVICE, DEFAULT_PER_PIN_DEVICE
            )
            
            # Create the entry (save options)
            result = self.async_create_entry(title="", data=user_input)
            
            # Reload if per_pin_device changed
            if per_pin_device_changed:
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self.config_entry.entry_id)
                )
            
            return result

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PER_PIN_DEVICE,
                    default=self.config_entry.options.get(
                        CONF_PER_PIN_DEVICE,
                        DEFAULT_PER_PIN_DEVICE
                    ),
                ): bool,
                vol.Optional(
                    CONF_INVERT_LOGIC,
                    default=self.config_entry.options.get(
                        CONF_INVERT_LOGIC, DEFAULT_INVERT_LOGIC
                    ),
                ): bool,
            }
        )
        if self.config_entry.data[CONF_FLOW_PLATFORM] == "binary_sensor":
            data_schema = data_schema.extend(
                {
                    vol.Optional(
                        CONF_PULL_MODE,
                        default=self.config_entry.options.get(
                            CONF_PULL_MODE, DEFAULT_PULL_MODE
                        ),
                    ): vol.In([MODE_UP, MODE_DOWN]),
                }
            )

        if self.config_entry.data[CONF_FLOW_PLATFORM] == "switch":
            data_schema = data_schema.extend(
                {
                    vol.Optional(
                        CONF_HW_SYNC,
                        default=self.config_entry.options.get(
                            CONF_HW_SYNC, DEFAULT_HW_SYNC
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_MOMENTARY,
                        default=self.config_entry.options.get(
                            CONF_MOMENTARY, DEFAULT_MOMENTARY
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_PULSE_TIME,
                        default=self.config_entry.options.get(
                            CONF_PULSE_TIME, DEFAULT_PULSE_TIME
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0)),
                }
            )
        return self.async_show_form(step_id="init", data_schema=data_schema)
