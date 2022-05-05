# HA-mcp23017
Improved MCP23017 implementation for Home Assistant

## Highlights of what it does offer

- **Async** implementation (more reactive and nicer to HA)
- **Thread-safety** allows different entities to use the same component
- **Config Flow** support (UI configuration) in addition to legacy configuration.yaml.
- **Push iso pull model** for higher reactivity, e.g. 100ms polling for 'zero-delay' push button without loading HA.
- Optimized i2c bus bandwidth utilisation
  - Polling per device instead of per entity/8x gain, register cache to avoid read-modify-write/3xgain or rewriting the same register value)
- Synchronization with the device state at startup, e.g. avoid output glitches when HA restart.

## Installation

### Using [HACS](https://hacs.xyz/)

1. Add https://github.com/jpcornil-git/HA-mcp23017 to your [custom repositories](https://hacs.xyz/docs/faq/custom_repositories/)

### Update custom_components folder

1. Clone or download all files from this repository 
2. Move custom_components/mcp23017 to your <ha_configuration_folder>, e.g. /home/homeassistant/.homeassistant/custom_components/mcp23017
3. Restart HA and clear browser cache (or restart a browser); latter is required for new config_flow to show up
4. Add mcp23017 component using:
   - **config flow** (Configuration->Integrations->Add integration)
     - Created entities will be visible in the **Integrations** tab and aggregated per device (i2c address) in the **Devices** tab.
     - Entity parameters (invert logic, pull-up, ...) can be adapted using the entity's **Options** button once created.
   - **configuration.yaml** see configuration example below.
     - Syntax is compatible with the now defunct core implementation (removed by https://github.com/home-assistant/core/pull/67281)
       - Added **hw_sync** to synchronize initial value with hardware (true, default) or to a fixed value (false, value=invert_logic)
     - Entity parameters (invert logic, pull-up, ...) can only be set globally for all pins of a device/integration.

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
    hw_sync: false
    pins:
      0 : Output_4
      1 : Output_5
      2 : Output_6
      3 : Output_7
```
