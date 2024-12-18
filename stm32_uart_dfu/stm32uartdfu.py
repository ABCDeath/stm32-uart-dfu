from collections import Sequence
from functools import reduce, wraps
from operator import xor
from typing import Callable, Dict, List, NoReturn, Union

import serial

from . import exceptions


def _retry(retry_num: int = 0, action: str = '', exc_call: Callable = None):
    def decorator(func: Callable):
        @wraps(func)
        def retry_wrapper(*args, **kwargs):
            for current_retry in range(retry_num):
                try:
                    ret = func(*args, **kwargs)
                except exceptions.DfuException as ex:
                    if exc_call:
                        exc_call(args[0])
                    last_caught = ex
                else:
                    return ret
            else:
                raise exceptions.DfuException(
                    'Error: {} failed after {} retries.'.format(
                        action, retry_num
                    )
                ) from last_caught

        return retry_wrapper

    return decorator


class Stm32UartDfu:
    """ST microelectronics uart dfu handler."""

    _DEFAULT_PARAMETERS = {
        'baudrate': 115200,
        'parity': 'E',
        'timeout': 1  # seconds
    }

    _RESPONSE_SIZE = 1
    _RW_MAX_SIZE = 256
    _RETRIES = 3

    _RESPONSE = {
        'ack': 0x79.to_bytes(length=1, byteorder='little'),
        'nack': 0x1f.to_bytes(length=1, byteorder='little')
    }

    _COMMAND = {
        'get version': 0x0,
        'get version and protection status': 0x01,
        'get id': 0x02,
        'read memory': 0x11,
        'go': 0x21,
        'write memory': 0x31,
        'erase': 0x43,
        'extended erase': 0x44,
        'write protect': 0x63,
        'write unprotect': 0x73,
        'readout protect': 0x82,
        'readout unprotect': 0x92
    }

    def __init__(self, port: str):
        self._port_handle = serial.Serial(
            port=port, baudrate=self._DEFAULT_PARAMETERS['baudrate'],
            parity=self._DEFAULT_PARAMETERS['parity'],
            timeout=self._DEFAULT_PARAMETERS['timeout']
        )

        if not self._port_handle.isOpen():
            raise serial.SerialException("Can't open serial port.")

        self._uart_dfu_init()

        self._id = None
        self._version = None
        self._commands = None
        self._read_protection_status = None

    def __delete__(self):
        if self._port_handle.isOpen():
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, *_, **__):
        if self._port_handle.isOpen():
            self.close()

    @staticmethod
    def _checksum(data: Union[int, Sequence], init: int = 0) -> bytes:
        if isinstance(data, Sequence):
            val = reduce(xor, data, init)
        else:
            val = 0xff - data

        return (0xff & val).to_bytes(1, 'big')

    def _check_acknowledge(self) -> bool:
        """
        Read dfu answer and checks if it is an acknowledge byte.
        :return: True if acknowledge byte was received.
        :raise: DfuAcknowledgeException if device did not respond with ack.
        """

        response = self._port_handle.read()
        if not response or response != self._RESPONSE['ack']:
            raise exceptions.DfuAcknowledgeException(response)

        return True

    def _serial_write(self, data: bytes) -> NoReturn:
        done = self._port_handle.write(data)
        if done != len(data):
            raise exceptions.DfuSerialIOException(len(data), done)

    def _serial_read(self, amount: int = 0) -> bytes:
        data = (self._port_handle.read(amount) if amount
                else self._port_handle.read())
        if amount and len(data) != amount:
            raise exceptions.DfuSerialIOException(amount, len(data))

        return data

    def _serial_flush(self) -> NoReturn:
        self._port_handle.flushInput()
        self._port_handle.flushOutput()

    @_retry(_RETRIES, 'DFU init', _serial_flush)
    def _uart_dfu_init(self) -> NoReturn:
        """Send uart dfu init byte and waits for acknowledge answer."""

        self._serial_write(0x7f.to_bytes(1, 'big'))
        self._check_acknowledge()

    @_retry(_RETRIES, 'send dfu command', _serial_flush)
    def _send_command(self, command: int) -> NoReturn:
        """Send command with checksum, waits for acknowledge."""

        self._serial_write(
            b''.join([command.to_bytes(1, 'big'), self._checksum(command)])
        )
        self._check_acknowledge()

    def _set_address(self, address: int) -> NoReturn:
        """
        Send address with checksum for read, write and erase commands.
        :param address: int
        """

        self._serial_write(
            b''.join(
                [address.to_bytes(4, 'big'),
                    self._checksum(address.to_bytes(4, 'big'))]
            )
        )
        self._check_acknowledge()

    @_retry(_RETRIES, 'read memory', _serial_flush)
    def _read_memory_chunk(self, address: int, size: int) -> bytes:
        self._send_command(self._COMMAND['read memory'])
        self._set_address(address)

        self._port_handle.write(
            b''.join([(size - 1).to_bytes(1, 'big'), self._checksum(size - 1)])
        )
        self._check_acknowledge()

        return self._serial_read(size)

    @_retry(_RETRIES, 'write memory', _serial_flush)
    def _write_memory_chunk(self, address: int, data: bytes) -> NoReturn:
        self._send_command(self._COMMAND['write memory'])
        self._set_address(address)

        self._serial_write((len(data) - 1).to_bytes(1, 'big'))
        self._serial_write(data)
        self._serial_write(self._checksum(data, len(data) - 1))

        self._check_acknowledge()

    @_retry(_RETRIES, 'erase', _serial_flush)
    def _perform_erase(self, parameters: bytes) -> NoReturn:
        self._serial_write(parameters)

        port_settings = self._port_handle.getSettingsDict()
        port_settings['timeout'] = 5 * 60
        self._port_handle.applySettingsDict(port_settings)

        try:
            self._check_acknowledge()
        finally:
            port_settings['timeout'] = self._DEFAULT_PARAMETERS['timeout']
            self._port_handle.applySettingsDict(port_settings)

    # dfu properties

    @property
    @_retry(_RETRIES, 'get mcu id', _serial_flush)
    def id(self) -> bytes:
        """
        Read MCU ID.
        :return: product id
        """

        if self._id:
            return self._id

        self._send_command(self._COMMAND['get id'])

        size = int.from_bytes(self._serial_read(1), 'big') + 1
        pid = self._serial_read(size)

        self._check_acknowledge()

        self._id = pid

        return pid

    @property
    @_retry(_RETRIES, 'get dfu version', _serial_flush)
    def version(self) -> bytes:
        """
        Read dfu version and available commands.
        :return: version: dfu version
        """

        if self._version:
            return self._version

        self._send_command(self._COMMAND['get version'])

        size = int.from_bytes(self._serial_read(1), 'big')

        version = self._serial_read(1)
        commands = self._serial_read(size)

        self._check_acknowledge()

        self._version = version
        self._commands = commands

        return version

    @property
    def commands(self) -> bytes:
        if not self._commands:
            _ = self.version

        return self._commands

    @property
    @_retry(_RETRIES, 'get extended dfu version', _serial_flush)
    def read_protection_status(self) -> bytes:
        """
        Read dfu version and read protection status bytes.
        :return: read_protection_status: read protection status
        """

        if self._read_protection_status:
            return self._read_protection_status

        self._send_command(self._COMMAND['get version and protection status'])

        read_protection_status = self._serial_read(3)[1:]

        self._check_acknowledge()

        self._read_protection_status = read_protection_status

        return read_protection_status

    # public methods

    def close(self) -> NoReturn:
        self._port_handle.close()

    @_retry(_RETRIES, 'go', _serial_flush)
    def go(self, address: int) -> NoReturn:
        """
        Run MCU from memory defined by address parameter.
        :param address: address to jump
        """

        self._send_command(self._COMMAND['go'])
        self._set_address(address)

    def read(
        self, address: int = None, size: int = None,
        progress_update: Callable = lambda *_: None, *,
        memory_map: List[Dict[str, str]] = None
    ) -> bytes:
        """
        Read %size% bytes of memory from %address%.
        :param address: address to start reading
        :param size: size of memory to be dumped
        :param progress_update: callable to update progressbar, default: None
        :param memory_map: {'address': 'value', 'size': 'value'} -
            mcu memory sectors addresses with size
        :return: memory dump
        """

        address = address if address else int(memory_map[0]['address'], 0)
        if not size:
            size = (int(memory_map[-1]['address'], 0) +
                    int(memory_map[-1]['size'], 0) - address)

        size_remain = size
        data = b''

        while size_remain:
            progress_update(int(100 * (size - size_remain) / size))

            part_size = min(self._RW_MAX_SIZE, size_remain)
            offset = address + size - size_remain

            data = b''.join([data, self._read_memory_chunk(offset, part_size)])

            size_remain -= part_size

        progress_update(100)

        return data

    def write(
        self, address: int, data: Union[bytes, bytearray],
        progress_update: Callable = lambda *_: None
    ):
        """Loads %data% to mcu memory at %address%."""
        size_remain = len(data)

        while size_remain:
            progress_update(int(100 * (len(data) - size_remain) / len(data)))

            part_size = min(self._RW_MAX_SIZE, size_remain)
            offset = address + len(data) - size_remain
            chunk = data[offset - address: offset - address + part_size]

            self._write_memory_chunk(offset, chunk)

            size_remain -= part_size

        progress_update(100)

    def erase(
        self, address: int = None, size: int = None,
        memory_map: List[Dict[str, str]] = None,
        progress_update: Callable = lambda *_: None
    ):
        """
        Erases mcu memory. Memory can be erased only by pages,
        so the whole pages containing start and stop addresses will be erased.
        :param address: erase starting address
        :param size: size of memory to be erased
        :param memory_map: {'address': 'value', 'size': 'value'} -
            mcu memory sectors addresses with size
        :param progress_update: Callable to update progressbar, default: None
        """

        if not size and not address:
            mass_erase = b'\xff\xff'
            parameters = b''.join([mass_erase, self._checksum(mass_erase)])
        else:
            if not memory_map:
                raise AttributeError(
                    "Can't erase specified size of memory without memory map."
                )

            try:
                start = [
                    i for i, sector in enumerate(memory_map)
                    if (int(sector['address'], 0) <= address <
                        int(sector['address'], 0) + int(sector['size'], 0))
                ][0]

                end = [
                    i for i, sector in enumerate(memory_map)
                    if (int(sector['address'], 0) < address + size <=
                        int(sector['address'], 0) + int(sector['size'], 0))
                ][0]
            except IndexError:
                raise AttributeError(
                    'Erase memory failed: can not find boundaries '
                    'for specified size and memory map.'
                )

            sectors = [s.to_bytes(2, 'big') for s in range(start, end + 1)]

            parameters = b''.join([(end - start).to_bytes(2, 'big'), *sectors])
            parameters = b''.join([parameters, self._checksum(parameters)])

        self._send_command(self._COMMAND['extended erase'])
        self._perform_erase(parameters)

        progress_update(100)
