# HA-mcp23017
MCP23008/MCP23017 implementation for Home Assistant (HA)

## Highlights of what it does offer

- **Async** implementation (more reactive and nicer to HA)
- **Thread-safety** allows different entities to use the same component
- **Config Flow** support (UI configuration) in addition to legacy configuration.yaml.
- **Push iso pull model** for higher reactivity, e.g. 100ms polling for 'zero-delay' push button without loading HA.
- Optimized i2c bus bandwidth utilisation
  - Polling per device instead of per entity/8x gain, register cache to avoid read-modify-write/3xgain or rewriting the same register value)
- Synchronization with the device state at startup, e.g. avoid output glitches when HA restart.
- Compatible with **MCP23008** device (8 pins variant).

## Installation

### 1. Add this MCP23017 integration to HA 
* Using [HACS](https://hacs.xyz/)
    * Add https://github.com/jpcornil-git/HA-mcp23017 to your [custom repositories](https://hacs.xyz/docs/faq/custom_repositories/)
* Or by updating manually your custom_components folder
    * Clone or download this repository 
    * Move custom_components/mcp23017 to your <ha_configuration_folder>, e.g. /home/homeassistant/.homeassistant/custom_components/mcp23017
    * Restart HA and clear browser cache (or restart a browser); latter is required for new config_flow to show up
### 2. Add your mcp23017 component(s) using either:
   - **config flow** (Configuration->Integrations->Add integration)
     - Created entities will be visible in the **Integrations** tab and aggregated per device (i2c address) in the **Devices** tab.
     - Entity parameters (invert logic, pull-up, ...) can be adapted individually by using the entity's **Options** button once created.
   - **configuration.yaml** see configuration example below.
     - Syntax is compatible with the now defunct core implementation (removed by https://github.com/home-assistant/core/pull/67281)
       - New **hw_sync** option allowing to either synchronize initial value of the switch with the hardware (true, default option) or to set it to a fixed value (false, value=invert_logic)
     - Entity parameters (invert logic, pull-up, ...) can only be set globally for all pins of a given device/integration.

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
