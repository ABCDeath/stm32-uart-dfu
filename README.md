# stm32-uart-dfu
Simple command-line program to work with stm32 microcontrollers uart bootloader.

## Usage:
Available dfu operations:
 - get id: prints mcu id (2 bytes)
 - run: MCU jumps at specified address
 - erase: erase specified size of memory at address
 - dump: dump specified size of memory to a file from address
 - load: load binary file to memory at address.

### For available commands:
```
> python3 stm32-uart-dfu.py --help
```

### For specific command help:
```
> python3 stm32-uart-dfu.py load --help
```

### Example:
```
> python3 stm32-uart-dfu.py --port /dev/ttyUSB0 load --file firmware.bin --erase -m map.json
```

### Memory map file:
Memory map file contains mcu's flash memory sectors information (address, size). Table with flash memory organization can be found in reference manual in 'embedded flash memory' section.  
For example memory_map.json for stm32f407:
``` json
[
  {
    "address": "0x8000000",
    "size": "0x4000"
  },
  {
    "address": "0x8004000",
    "size": "0x4000"
  },
  {
    "address": "0x8008000",
    "size": "0x4000"
  },
  {
    "address": "0x800c000",
    "size": "0x4000"
  },
  {
    "address": "0x8010000",
    "size": "0x10000"
  },
  {
    "address": "0x8020000",
    "size": "0x20000"
  },
  {
    "address": "0x8040000",
    "size": "0x20000"
  },
  {
    "address": "0x8060000",
    "size": "0x20000"
  },
  {
    "address": "0x8080000",
    "size": "0x20000"
  },
  {
    "address": "0x80a0000",
    "size": "0x20000"
  },
  {
    "address": "0x80c0000",
    "size": "0x20000"
  },
  {
    "address": "0x80e0000",
    "size": "0x20000"
  }
]
```  
If memory map file is not passed to program, load operation will cause mass erase.
