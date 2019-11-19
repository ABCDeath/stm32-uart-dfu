# stm32-uart-dfu
Simple command-line tool that works with stm32 microcontrollers
uart bootloader. Requires Python 3.6.

## Installing dependencies and usage:
To install python and dependencies you can use [pyenv](https://github.com/pyenv/pyenv) and [poetry](https://poetry.eustace.io/) ([pyenv-virtualenv plugin](https://github.com/pyenv/pyenv-virtualenv) for virtual environment). Or, alternatively, just run:
```bash
piip install -r requirements.txt
```  

### Usage
Available dfu operations:
 - get id: prints mcu id (2 bytes)
 - run: MCU jumps at specified address
 - erase: erase specified size of memory at address
 - dump: dump specified size of memory from address to a file
 - load: load binary file to memory at address.

#### To get all available commands:
```
> python3 uart-dfu.py --help
```  

#### To get specific command help:
```
> python3 uart-dfu.py load --help
```  

#### Example:
```
> python3 uart-dfu.py --port /dev/ttyUSB0 load --file firmware.bin --erase -m map.json
```  

#### Memory map file:
Memory map file contains mcu's flash memory sectors information (address, size).
Table with flash memory organization can be found in reference manual in
'embedded flash memory' section.  
json file with memory map example for stm32f407 can be found in memory_map directory.
Basically this file contains list of dicts like that:
```json
[
  {
    "address": "0x8000000",
    "size": "0x4000"
  },
  {
    "address": "0x8004000",
    "size": "0x4000"
  },
  ...
]
```  
Without memory map only mass erase is available.
