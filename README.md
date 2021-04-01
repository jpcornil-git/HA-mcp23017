# HA-mcp23017
Improved MCP23017 implementation for Home Assistant

## Overview
- **Async code** is implemented in entities while sync code ('mcp23017 device driver') is implemented in ```__init__.py``` .
- **Code is threadsafe** and allows different entities to use the same component (fix issue [#31867](https://github.com/home-assistant/core/issues/31867)).
- **Config Flow** is now supported in addition to legacy configuration.yaml.
- **Push iso pull model** is used for Async entities, active polling implemented in the sync code.
  - offer much higher reactivity, e.g. 100ms polling for 'zero-delay' push button, without loading HA.
- Dependencies towards all AdaFruit libraries have been removed.
  - mcp23017 integration can now run on a std linux machine (and be tested using i2c_stub module).
- Optimized i2c bus bandwidth by reducing number of transactions (polling per device instead of per entity/8x gain, register cache to avoid read-modify-write/3xgain or rewriting the same register value).
- Synchronization with the device state at startup, e.g. avoid output glitches when HA restart.

## Installation (while waiting for HACS integration)

1. Clone or download all files from this repository 
2. Move custom_components/mcp23017 to your <ha_configuration_folder>, e.g. /home/homeassistant/.homeassistant/custom_components/mcp23017
3. Restart HA and clear browser cache (or restart a browser); latter is required for new config_flow to show up
4. Add mcp23017 component using:
- **config flow** (Configuration->Integrations->Add integration) [preferred]
Created entities will be visible in the **Integrations** tab and aggregated per device (i2c address) in the **Devices** tab. Entity options (invert logic, pull-up, ...) can be adapted using the entity's **Options** button once created.
- **configuration.yaml** as illustrated below. Syntax is compatible with the legacy implementation described in https://www.home-assistant.io/integrations/mcp23017/

## Example entry for `configuration.yaml`:

```yaml
# Example configuration.yaml

binary_sensor:
  - platform: mcp23017
    i2c_address: 0x26
    pins:
      8 : Button_0
      9 : Button_1
      10: Button_2
      11: Button_3
  - platform: mcp23017
    i2c_address: 0x27
    invert_logic: true
    pins:
      8: Button_4
      9: Button_5
      10: Button_6
      11: Button_7

switch:
  - platform: mcp23017
    i2c_address: 0x26
    pins:
      0 : Output_0
      1 : Output_1
      2 : Output_2
      3 : Output_3
  - platform: mcp23017
    i2c_address: 0x27
    pins:
      0 : Output_4
      1 : Output_5
      2 : Output_6
      3 : Output_7
```
