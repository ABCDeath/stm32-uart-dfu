import argparse
import collections
import json
import time
import zlib
from threading import Thread
from functools import reduce

import serial


class DfuException(Exception):
    pass


class DfuAcknowledgeException(DfuException):
    """Dfu exception class for any acknowledgement issues."""

    def __init__(self, answer):
        super().__init__(f'Acknowledge error (dfu answer: {answer}')


class DfuSerialIOException(DfuException, serial.SerialException):
    """
    Dfu exception for serial io issues
    like tried to write n bytes, m<n written instead.
    """

    def __init__(self, expected, actual):
        super().__init__(f'Serial IO error: tried to transfer '
                         f'{expected}, {actual} was done.')


def _retry(retry_num=0, action='', exc_call=None):
    def decorator(func):
        def retry_wrapper(*args, **kwargs):
            for current_retry in range(retry_num):
                try:
                    ret = func(*args, **kwargs)
                except DfuException as ex:
                    if exc_call:
                        exc_call(*args)
                    last_caught = ex
                else:
                    return ret
            else:
                raise DfuException(
                    f'Error: {action} '
                    f'failed after {retry_num} retries.') from last_caught

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
            timeout=self._DEFAULT_PARAMETERS['timeout'])

        if not self._port_handle.isOpen():
            raise serial.SerialException("Can't open serial port.")

        self._uart_dfu_init()

    def __delete__(self):
        if self._port_handle.isOpen():
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._port_handle.isOpen():
            self.close()

    @staticmethod
    def _checksum(data, init=0):
        if isinstance(data, collections.Sequence):
            val = reduce(lambda accum, current: accum ^ current, data, init)
        else:
            val = 0xff - data

        return (0xff & val).to_bytes(1, 'big')

    def _check_acknowledge(self):
        """
        Reads dfu answer and checks is it acknowledge byte or not.
        :return:
            bool - True if acknowledge byte was received, otherwise False.
        """

        response = self._port_handle.read()
        if not response or response != self._RESPONSE['ack']:
            raise DfuAcknowledgeException(response)

    def _serial_write(self, data):
        done = self._port_handle.write(data)
        if done != len(data):
            raise DfuSerialIOException(len(data), done)

    def _serial_read(self, amount=0):
        data = (self._port_handle.read(amount) if amount
                else self._port_handle.read())
        if amount and len(data) != amount:
            raise DfuSerialIOException(amount, len(data))

        return data

    def _serial_flush(self):
        self._port_handle.flushInput()
        self._port_handle.flushOutput()

    @_retry(_RETRIES, 'DFU init', _serial_flush)
    def _uart_dfu_init(self):
        """Sends uart dfu init byte and waits for acknowledge answer."""

        self._serial_write(0x7f.to_bytes(1, 'big'))
        self._check_acknowledge()

    @_retry(_RETRIES, 'send dfu command', _serial_flush)
    def _send_command(self, command):
        """Sends command with checksum, waits for acknowledge."""

        self._serial_write(
            b''.join([command.to_bytes(1, 'big'), self._checksum(command)]))
        self._check_acknowledge()

    def _set_address(self, address):
        """
        Sends address with checksum for read, write and erase commands.
        :param address: int
        """

        self._serial_write(
            b''.join([address.to_bytes(4, 'big'),
                      self._checksum(address.to_bytes(4, 'big'))]))
        self._check_acknowledge()

    @_retry(_RETRIES, 'read memory', _serial_flush)
    def _read_memory_chunk(self, offset, size):
        self._send_command(self._COMMAND['read memory'])
        self._set_address(offset)

        self._port_handle.write(
            b''.join([(size - 1).to_bytes(1, 'big'), self._checksum(size - 1)]))
        self._check_acknowledge()

        return self._serial_read(size)

    @_retry(_RETRIES, 'write memory', _serial_flush)
    def _write_memory_chunk(self, offset, data):
        self._send_command(self._COMMAND['write memory'])
        self._set_address(offset)

        self._serial_write((len(data) - 1).to_bytes(1, 'big'))
        self._serial_write(data)
        self._serial_write(self._checksum(data, len(data) - 1))

        self._check_acknowledge()

    @_retry(_RETRIES, 'erase', _serial_flush)
    def _perform_erase(self, parameters):
        self._serial_write(parameters)

        port_settings = self._port_handle.getSettingsDict()
        port_settings['timeout'] = 5 * 60
        self._port_handle.applySettingsDict(port_settings)

        try:
            self._check_acknowledge()
        finally:
            port_settings['timeout'] = self._DEFAULT_PARAMETERS['timeout']
            self._port_handle.applySettingsDict(port_settings)

    # public methods

    def close(self):
        self._port_handle.close()

    @_retry(_RETRIES, 'get mcu id', _serial_flush)
    def get_id(self):
        """
        Reads MCU ID.
        :return:
            bytes - product id
        """

        self._send_command(self._COMMAND['get id'])

        size = int.from_bytes(self._serial_read(1), 'big') + 1
        pid = self._serial_read(size)

        self._check_acknowledge()

        return pid

    @_retry(_RETRIES, 'get dfu version', _serial_flush)
    def get_version(self):
        """
        Reads dfu version and available commands.
        :return:
            version: bytes - dfu version
            commands: bytes - dfu available commands
        """

        self._send_command(self._COMMAND['get version'])

        size = int.from_bytes(self._serial_read(1), 'big')

        version = self._serial_read(1)
        commands = self._serial_read(size)

        self._check_acknowledge()

        return version, commands

    @_retry(_RETRIES, 'get extended dfu version', _serial_flush)
    def get_version_extended(self):
        """
        Reads dfu version and read protection status bytes.
        :return:
            version: bytes - dfu version
            read_protection_status: bytes - read protection status
        """

        self._send_command(self._COMMAND['get version and protection status'])

        version = self._serial_read(1)
        read_protection_status = self._serial_read(2)

        self._check_acknowledge()

        return version, read_protection_status

    @_retry(_RETRIES, 'go', _serial_flush)
    def go(self, address):
        """
        Runs MCU from memory defined by address parameter.
        :param address: int - address to jump
        """

        self._send_command(self._COMMAND['go'])
        self._set_address(address)

    def read(self, address, size, progress_update=lambda *args: None):
        """
        Reads %size% bytes of memory from %address%.
        :param address: int - address to start reading
        :param size: int - size of memory to be dumped
        :param progress_update: function - function to update progressbar
            default: None
        :return: bytearray - memory dump
        """

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

    def write(self, address, data, progress_update=lambda *args: None):
        """
        Loads %data% to mcu memory at %address%.
        :param address: int
        :param data: bytes or bytearray
        :param progress_update: function - function to update progressbar
            default: None
        """
        size_remain = len(data)

        while size_remain:
            progress_update(int(100 * (len(data) - size_remain) / len(data)))

            part_size = min(self._RW_MAX_SIZE, size_remain)
            offset = address + len(data) - size_remain
            chunk = data[offset - address: offset - address + part_size]

            self._write_memory_chunk(offset, chunk)

            size_remain -= part_size

        progress_update(100)

    def erase(self, address, size=None, memory_map=None,
              progress_update=lambda *args: None):
        """
        Erases mcu memory. Memory can be erased only by pages,
        so the whole pages containing start and stop addresses will be erased.
        :param address: int - erase starting address
        :param size: int - size of memory to be erased
        :param memory_map: list of dicts {address: value, size: value} -
            mcu memory sectors addresses with size
        :param progress_update: function - function to update progressbar
            default: None
        """

        self._send_command(self._COMMAND['extended erase'])

        if not size:
            mass_erase = b'\xff\xff'
            parameters = b''.join([mass_erase, self._checksum(mass_erase)])
        else:
            if not memory_map:
                raise AttributeError(
                    "Can't erase specified size of memory without memory map.")

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
                    'for specified size and memory map.')

            sectors = [s.to_bytes(2, 'big') for s in range(start, end + 1)]

            parameters = b''.join([(end - start).to_bytes(2, 'big'), *sectors])
            parameters = b''.join([parameters, self._checksum(parameters)])

        self._perform_erase(parameters)

        progress_update(100)


class ProgressBar:
    _BAR_MAX_LEN = 40
    _ENDLESS_BAR_LEN = 20

    def __init__(self, endless: bool = False):
        self._endless = endless
        self._position = 0
        self._bar_len = 0
        self._reverse_direction = False

    def _complete_len(self, progress):
        return int(self._BAR_MAX_LEN * progress / 100)

    def _incomplete_len(self, progress):
        return self._BAR_MAX_LEN - self._complete_len(progress)

    def _print(self, progress=None):
        if progress == -1:
            print(f'\r[{"-"*self._BAR_MAX_LEN}] failed.')
        elif progress == 100:
            print(f'\r[{"█"*self._BAR_MAX_LEN}] done.')
        else:
            if self._endless:
                tail = self._BAR_MAX_LEN - self._bar_len - self._position
                print(
                    f'\r[{" "*self._position}{"█"*self._bar_len}'
                    f'{" "*tail}] ...',
                    end='')
            else:
                print(
                    f'\r[{"█"*self._complete_len(progress)}'
                    f'{" "*self._incomplete_len(progress)}] {progress}%',
                    end='')

    def is_endless(self):
        return self._endless

    def update(self, progress=None):
        if self._endless:
            if self._reverse_direction:
                if self._position > 0:
                    self._position -= 1
                    if self._bar_len < self._ENDLESS_BAR_LEN:
                        self._bar_len += 1
                elif self._bar_len > 0:
                    self._bar_len -= 1
                else:
                    self._reverse_direction = False
            else:
                if not self._position and self._bar_len < self._ENDLESS_BAR_LEN:
                    self._bar_len += 1
                elif self._position + self._bar_len < self._BAR_MAX_LEN:
                    self._position += 1
                elif self._bar_len > 0:
                    self._bar_len -= 1
                    self._position += 1
                else:
                    self._reverse_direction = True

        self._print(progress)


class ProgressBarThread(Thread):
    _WAKE_PERIOD = 0.2

    def __init__(self, endless=False):
        super().__init__(target=self._run)
        self._bar = ProgressBar(endless)
        self._progress = None if endless else 0
        super().start()

    def _run(self):
        while True:
            self._bar.update(self._progress)
            if self._progress == 100 or self._progress == -1:
                break
            time.sleep(self._WAKE_PERIOD)

    def update(self, progress):
        self._progress = progress


class DfuCommandHandler:
    @staticmethod
    def _abort(bar_thread=None):
        if bar_thread:
            bar_thread.update(-1)
            bar_thread.join()

        print('An Error occurred Reset MCU and try again.')

    @staticmethod
    def get_id(dfu, args):
        print('MCU ID: 0x{}'.format(dfu.get_id().hex()))

    @staticmethod
    def run(dfu, args):
        print(f'MCU will be running from {args.address}.')

        dfu.go(int(args.address, 0))

    def erase(self, dfu, args):
        if args.memory_map:
            with open(args.memory_map, 'r') as map_file:
                mem_map = json.load(map_file)
        else:
            mem_map = None

        if args.size:
            print(f'Erasing {args.size} bytes from {args.address}...')
        else:
            print('Erasing whole memory...')

        bar_thread = ProgressBarThread(endless=True)

        try:
            dfu.erase(int(args.address, 0), int(args.size, 0),
                      mem_map, bar_thread.update)
        except DfuException:
            self._abort(bar_thread)
            raise

        bar_thread.join()

    def dump(self, dfu, args):
        print(f'Dumping {args.size} bytes from {args.address}...')

        bar_thread = ProgressBarThread()

        try:
            with open(args.file, 'wb') as dump:
                dump.write(dfu.read(int(args.address, 0), int(args.size, 0),
                                    bar_thread.update))
        except DfuException:
            self._abort(bar_thread)
            raise

        bar_thread.join()

    def load(self, dfu, args):
        with open(args.file, 'rb') as firmware_file:
            firmware = firmware_file.read()

        if args.erase:
            if args.memory_map:
                with open(args.memory_map, 'r') as map_file:
                    mem_map = json.load(map_file)

                erase_size = len(firmware)

                print(f'Erasing {erase_size} bytes from {args.address}...')
            else:
                print('Erasing whole memory...')
                mem_map = None
                erase_size = None

            bar_thread = ProgressBarThread(endless=True)

            try:
                dfu.erase(int(args.address, 0), erase_size, mem_map,
                          bar_thread.update)
            except DfuException:
                self._abort(bar_thread)
                raise

            bar_thread.join()

        print(f'Loading {args.file} ({len(firmware)} bytes) at {args.address}')

        bar_thread = ProgressBarThread()

        try:
            dfu.write(int(args.address, 0), firmware, bar_thread.update)
        except DfuException:
            self._abort(bar_thread)
            raise

        bar_thread.join()

        print('Validating firmware...')

        bar_thread = ProgressBarThread()

        try:
            dump = dfu.read(int(args.address, 0), len(firmware),
                            bar_thread.update)
        except DfuException:
            self._abort(bar_thread)
            raise

        bar_thread.join()

        if zlib.crc32(firmware) != zlib.crc32(dump):
            print('Error: checksum mismatch!')
        else:
            print('Success!')

        if args.run:
            print(f'MCU will be running from {args.address}.')

            try:
                dfu.go(int(args.address, 0))
            except DfuException:
                self._abort()
                raise


if __name__ == '__main__':
    _ARGS_HELP = {
        'address': 'Memory address for ',
        'size': 'Required size of memory to be ',
        'memmap': 'Json file, containing memory structure.'
                  'Format: [{"address": "value", "size": "value"}, ...]',
        'run': 'Run program after loading.',
        'erase': 'Erase memory enough to store firmware'
                 '(whole memory if no memory map).'
    }

    dfu_handler = DfuCommandHandler()

    arg_parser = argparse.ArgumentParser(description='Stm32 uart dfu utility.')

    arg_parser.add_argument(
        '-p', '--port', default='/dev/ttyUSB0',
        help='Serial port file (for example: /dev/ttyUSB0).')

    commands = arg_parser.add_subparsers()

    load_command = commands.add_parser('load')

    load_command.add_argument(
        '-a', '--address', default='0x8000000',
        help=' '.join([_ARGS_HELP['address'], 'loading binary file.']))

    load_command.add_argument('-e', '--erase', action='store_true',
                              help=_ARGS_HELP['erase'])

    load_command.add_argument('-f', '--file', help='Binary firmware file.')

    load_command.add_argument('-m', '--memory-map', default=None,
                              help=_ARGS_HELP['memmap'])

    load_command.add_argument('-r', '--run', action='store_true',
                              help=_ARGS_HELP['run'])

    load_command.set_defaults(func=dfu_handler.load)

    erase_command = commands.add_parser('erase')

    erase_command.add_argument(
        '-a', '--address', default='0x8000000',
        help=' '.join([_ARGS_HELP['address'], 'erasing.']))

    erase_command.add_argument('-m', '--memory-map', default=None,
                               help=_ARGS_HELP['memmap'])

    erase_command.add_argument('-s', '--size', default=None,
                               help=' '.join([_ARGS_HELP['size'], 'erased.']))

    erase_command.set_defaults(func=dfu_handler.erase)

    dump_command = commands.add_parser('dump')

    dump_command.add_argument('-a', '--address', default='0x8000000',
                              help=' '.join([_ARGS_HELP['address'], 'dump.']))

    dump_command.add_argument('-s', '--size', default=None,
                              help=' '.join([_ARGS_HELP['size'], 'dumped.']))

    dump_command.add_argument('-f', '--file',
                              help='Specify file for memory dump.')

    dump_command.set_defaults(func=dfu_handler.dump)

    get_id_command = commands.add_parser('id')

    get_id_command.set_defaults(func=dfu_handler.get_id)

    run_command = commands.add_parser('run')

    run_command.add_argument('-a', '--address', default='0x8000000',
                             help=' '.join([_ARGS_HELP['address'], 'run.']))

    run_command.set_defaults(func=dfu_handler.run)

    args = arg_parser.parse_args()

    with Stm32UartDfu(args.port) as dfu:
        args.func(dfu, args)
