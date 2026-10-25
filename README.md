# Fairland (Modbus) Integration for Home Assistant

[![GitHub Release](https://img.shields.io/github/release/hardes-bv/ha-fairland-modbus.svg)](https://github.com/hardes-bv/ha-fairland-modbus/releases)

This integration enables monitoring and control of Fairland pool equipment in Home Assistant — heat pumps, 
pool pumps (Inverflow Plus and OEM-rebadged variants such as Madimack), salt chlorinators, multiport (sand-filter) 
valves and swim jets — connecting locally to the devices via Modbus TCP or RTU.

## Supported devices

| Device | Status |
| --- | --- |
| Inverter pool heat pumps with an MWH216 or MWH298 board (Fairland IPHCR and InverX, and the same board under other brands, such as the Geco GEPAC08) | Climate entity: on and off, heat, cool and automatic, setpoints and working modes. The test package this code comes from ran on a GEPAC08 with an MWH298-V3 board. |

The device support comes from the [fairland-modbus](https://github.com/hardes-bv/python-fairland-modbus)
library, which Home Assistant installs from PyPI.

## Installation

Home Assistant 2026.10.2 or later: the test package this code comes from ran on 2026.10.2, and the tests run on 2026.10.3.

1. In HACS, open the menu, select **Custom repositories**, and add
   `https://github.com/hardes-bv/ha-fairland-modbus` as an **Integration**.
2. Install **Fairland (Modbus)**, then restart Home Assistant.

## Connecting the heat pump

The control board has a 4-pin RS485 port marked `B`, `A`, `G` and `+12V`. Wire it to
either:

- an RS485 to Modbus TCP gateway, set to **Modbus TCP to RTU**, 9600 baud, 8 data bits,
  no parity, 1 stop bit;
- or a USB RS485 adapter on the Home Assistant host.

Swap `A` and `B` if the heat pump does not answer. The board answers at Modbus address 1.

## Configuration

Go to **Settings** > **Devices & services** > **Add integration**, select
**Fairland (Modbus)**, then choose the network or the serial port and enter the gateway
address or the adapter.

## Development

```sh
uv venv --python 3.14
uv pip install -r requirements_test.txt
uv run --no-sync pytest
```

To pick up a new release of the library, update the `fairland-modbus` version in
`manifest.json` and `requirements_test.txt`.

## License
This project is licensed under the Apache v2 License - see the LICENSE file for details.
