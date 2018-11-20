import json
import pytest


@pytest.fixture(scope='module', params=['/dev/ttyUSB0'])
def dfu(request):
    import stm32uartdfu
    return stm32uartdfu.Stm32UartDfu(request.param)

@pytest.fixture(scope='module', params=['memory_map/stm32f407.json'])
def memory_map(request):
    with open(request.param) as map_file:
        return json.load(map_file)

def test_read_id(dfu):
    assert len(dfu.id) == 2 and dfu.id[0] == 4

def test_version(dfu):
    assert dfu.version

def test_read_protection_status(dfu):
    assert dfu.read_protection_status

def test_commands(dfu):
    assert b'\x00\x01\x02\x11\x21\x31\x44' in dfu.commands

@pytest.mark.parametrize("address,size", [
    (10, 20),
    (20, 2),
])
def test_erase(dfu, memory_map, address, size):
    pass

# TODO: write 3 sectors, erase first and check data in 0 and 2 sectors
# TODO: write 3 random amount of random data, check it
# TODO: perform mass erase
# TODO: load firmware, check it and run
