import json
import random

import pytest


@pytest.fixture(scope='module', params=['/dev/ttyUSB0'])
def dfu(request):
    import stm32uartdfu
    return stm32uartdfu.Stm32UartDfu(request.param)


@pytest.fixture(scope='module', params=['memory_map/stm32f407.json'])
def memory_map(request):
    with open(request.param) as map_file:
        return json.load(map_file)


@pytest.fixture(scope='module', params=['fw.bin'])
def firmware(request):
    with open(request.param, 'rb') as fw:
        return fw.read()


def test_read_id(dfu):
    assert len(dfu.id) == 2 and dfu.id[0] == 4


def test_version(dfu):
    assert dfu.version


def test_read_protection_status(dfu):
    assert dfu.read_protection_status


def test_commands(dfu):
    assert b'\x00\x01\x02\x11\x21\x31\x44' in dfu.commands


@pytest.mark.parametrize('address,size', [
    (0x8000040, 76543),
    (0x8008080, 96478),
])
def test_load_random(dfu, memory_map, address, size):
    data = b''.join([random.randint(0, 255).to_bytes(1, 'big')
                     for _ in range(size)])
    dfu.erase(address, size, memory_map)
    dfu.write(address, data)
    assert dfu.read(address, len(data)) == data


def test_erase(dfu, memory_map):
    dfu.erase()
    dump = dfu.read(memory_map=memory_map)
    assert dump.count(b'\xff') == len(dump)


def test_load_firmware(dfu, memory_map, firmware):
    address = 0x8000000
    dfu.erase(address, len(firmware), memory_map)
    dfu.write(address, firmware)
    assert firmware == dfu.read(address, len(firmware))
    dfu.go(address)
