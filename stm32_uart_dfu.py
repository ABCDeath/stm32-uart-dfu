import argparse
import json
import sys
import time
import zlib
from threading import Thread

import serial


class DfuException(Exception):
    def __init__(self, message=None):
        if message is None:
            message = 'An error occured in dfu.'
            super().__init__(message)


class Stm32UartDfu(object):
    __DEFAULT_PARAMETERS = {
        'baudrate': 115200,
        'parity': 'E',
        'timeout': 1  # seconds
    }

    __RESPONSE_SIZE = 1
    __RW_MAX_SIZE = 256
    __RETRY_MAX_NUM = 3

    __RESPONSE = {
        'ack': 0x79.to_bytes(length=1, byteorder='little'),
        'nack': 0x1f.to_bytes(length=1, byteorder='little')
    }

    __COMMAND = {
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

    def _checksum(self, data):
        try:
            _ = (item for item in data)
        except TypeError:
            checksum = 0xff - data
        else:
            checksum = 0
            for byte in data:
                checksum ^= byte

        return checksum

    def _is_acknowledged(self):
        response = self._port_handle.read(1)
        if len(response) == 0:
            raise DfuException('DFU did not send the answer.')
        else:
            if response != self.__RESPONSE['ack']:
                print('dfu answered nack (0x{})'.format(response.hex()))
        return response == self.__RESPONSE['ack']

    def _uart_dfu_init(self):
        __INIT_SEQUENCE = [0x7f]

        for retry in range(0, self.__RETRY_MAX_NUM):
            bytes_sent = self._port_handle.write(__INIT_SEQUENCE)
            if bytes_sent != len(__INIT_SEQUENCE):
                raise DfuException('Serial port write error: tried to send {} '
                                   'bytes, but {} was '
                                   'sent.'.format(len(__INIT_SEQUENCE),
                                                  bytes_sent))

            if self._is_acknowledged():
                break
        else:
            raise DfuException('Dfu init failed after {} '
                               'retries.'.format(retry + 1))

    def __init__(self, port):
        self._port_handle = \
            serial.Serial(port=port,
                          baudrate=self.__DEFAULT_PARAMETERS['baudrate'],
                          parity=self.__DEFAULT_PARAMETERS['parity'],
                          timeout=self.__DEFAULT_PARAMETERS['timeout'])
        if not self._port_handle.isOpen():
            raise DfuException('Serial port was not opened.')

        self._uart_dfu_init()

    def __delete__(self):
        if self._port_handle.isOpen():
            self._port_handle.close()

    def _send_command(self, command):
        command_sequence = [command, self._checksum(command)]

        for retry in range(0, self.__RETRY_MAX_NUM):
            bytes_sent = self._port_handle.write(command_sequence)
            if bytes_sent != len(command_sequence):
                raise DfuException('Serial port write error: tried to send {} '
                                   'bytes, but {} was '
                                   'sent.'.format(len(command_sequence),
                                                  bytes_sent))

            if self._is_acknowledged():
                break

            self._port_handle.flushInput()
            self._port_handle.flushOutput()
        else:
            raise DfuException(
                'Command {} failed after '
                '{} retries.'.format(hex(command), retry + 1))

    def _set_address(self, address):
        for retry in range(0, self.__RETRY_MAX_NUM):
            sequence = bytearray(address.to_bytes(4, 'big'))
            sequence.append(self._checksum(sequence))

            bytes_sent = self._port_handle.write(sequence)
            if bytes_sent != len(sequence):
                raise DfuException(
                    'Serial port write error: tried to'
                    'send {} bytes, but {} was sent.'.format(
                        len(sequence), bytes_sent))
            if self._is_acknowledged():
                break
        else:
            raise DfuException('Setting address failed after {} '
                               'retries.'.format(retry + 1))

    def get_id(self):
        for retry in range(0, self.__RETRY_MAX_NUM):
            self._send_command(self.__COMMAND['get id'])

            size = int.from_bytes(self._port_handle.read(1), 'little') + 1
            pid = self._port_handle.read(size)
            if self._is_acknowledged():
                return pid
        else:
            raise DfuException('Get id failed after {} '
                               'retries.'.format(retry + 1))

    def get_version(self):
        for retry in range(0, self.__RETRY_MAX_NUM):
            self._send_command(self.__COMMAND['get version'])

            size = int.from_bytes(self._port_handle.read(1), 'little')

            version = self._port_handle.read(1)
            commands = self._port_handle.read(size)
            if self._is_acknowledged():
                return version, commands
        else:
            raise DfuException('Get version failed after {} '
                               'retries.'.format(retry + 1))

    def get_version_extended(self):
        for retry in range(0, self.__RETRY_MAX_NUM):
            self._send_command(
                self.__COMMAND['get version and protection status'])

            version = self._port_handle.read(1)
            read_protection_status = self._port_handle.read(2)
            if self._is_acknowledged():
                return version, read_protection_status
        else:
            raise DfuException('Get extended version failed after {} '
                               'retries.'.format(retry + 1))

    def read(self, address, size, progress_update=None):
        size_remain = size
        data = bytearray()

        while size_remain > 0:
            if progress_update is not None:
                progress_update(int(100 * (size - size_remain) / size))

            part_size = self.__RW_MAX_SIZE \
                if size_remain > self.__RW_MAX_SIZE else size_remain
            offset = address + size - size_remain

            for retry in range(0, self.__RETRY_MAX_NUM):
                self._send_command(self.__COMMAND['read memory'])
                self._set_address(offset)

                self._port_handle.write(
                    [part_size - 1, self._checksum(part_size - 1)])
                if self._is_acknowledged():
                    break
            else:
                raise DfuException('Read memory at {} failed after {} '
                                   'retries.'.format(offset, retry + 1))

            chunk = self._port_handle.read(part_size)
            if len(chunk) != part_size:
                raise DfuException('Read {} bytes istead of '
                                   '{}.'.format(len(chunk), part_size))
            data.extend(bytearray(chunk))

            size_remain -= part_size

        if progress_update is not None:
            progress_update(100)

        return data

    def go(self, address):
        self._send_command(self.__COMMAND['go'])
        self._set_address(address)

    def write(self, address, data, progress_update=None):
        size_remain = len(data)

        while size_remain > 0:
            if progress_update is not None:
                progress_update(
                    int(100 * (len(data) - size_remain) / len(data)))

            part_size = self.__RW_MAX_SIZE \
                if size_remain > self.__RW_MAX_SIZE else size_remain
            offset = address + len(data) - size_remain

            for retry in range(0, self.__RETRY_MAX_NUM):
                self._send_command(self.__COMMAND['write memory'])
                self._set_address(offset)

                chunk = data[offset - address:offset - address + part_size]
                checksum = 0xff & ((part_size - 1) ^ self._checksum(chunk))

                bytes_sent = self._port_handle.write(bytearray([part_size - 1]))
                if bytes_sent != len(bytearray([part_size - 1])):
                    raise DfuException('Tried to send {} bytes, {} was '
                                       'sent.'.format(
                        len(bytearray([part_size - 1])),
                        bytes_sent))

                bytes_sent = self._port_handle.write(chunk)
                if bytes_sent != len(chunk):
                    raise DfuException('Tried to send {} bytes, {} was '
                                       'sent.'.format(len(chunk), bytes_sent))

                bytes_sent = self._port_handle.write(bytearray([checksum]))
                if bytes_sent != len(bytearray([checksum])):
                    raise DfuException('Tried to send {} bytes, {} was '
                                       'sent.'.format(
                        len(bytearray([checksum])),
                        bytes_sent))

                if self._is_acknowledged():
                    break
            else:
                raise DfuException('Write memory at {} failed after {} '
                                   'retries.'.format(offset, retry + 1))

            size_remain -= part_size

        if progress_update is not None:
            progress_update(100)

    def erase(self, address, size=None, memory_map=None, progress_update=None):
        self._send_command(self.__COMMAND['extended erase'])

        if size is None:
            command_parameters = [0xff, 0xff]
            command_parameters.append(self._checksum(command_parameters))
        else:
            if memory_map is None:
                raise DfuException('Only whole memory erase is possible '
                                   'without memory map.')

            for sector_num, sector_params in enumerate(memory_map):
                start = int(sector_params['address'], 0)
                end = start + int(sector_params['size'], 0)

                if start <= int(address, 0) < end:
                    erase_start = sector_num
                if start < int(address, 0) + int(size, 0) <= end:
                    erase_end = sector_num
                    break

            sectors_num = erase_end - erase_start
            sectors = [sector.to_bytes(2, 'big') for sector in
                       range(erase_start, erase_end + 1)]

            command_parameters = bytearray(sectors_num.to_bytes(2, 'big'))
            for sector in sectors:
                command_parameters.extend(bytearray(sector))
            command_parameters.append(self._checksum(command_parameters))

        for retry in range(0, self.__RETRY_MAX_NUM):
            bytes_sent = self._port_handle.write(command_parameters)
            if bytes_sent != len(command_parameters):
                raise DfuException('Tried to send {} bytes, {} was '
                                   'sent.'.format(len(command_parameters),
                                                  bytes_sent))

            port_settings = self._port_handle.getSettingsDict()
            port_settings['timeout'] = 5 * 60
            self._port_handle.applySettingsDict(port_settings)

            if self._is_acknowledged():
                port_settings['timeout'] = \
                    self.__DEFAULT_PARAMETERS['timeout']
                self._port_handle.applySettingsDict(port_settings)
                break
        else:
            raise DfuException('Erase memory failed after {} '
                               'retries.'.format(retry + 1))

        if progress_update is not None:
            progress_update(100)


class ProgressBar(object):
    _BAR_MAX_LEN = 40
    _ENDLESS_BAR_LEN = 20

    def __init__(self, endless=False):
        self._endless = endless
        self._position = 0
        self._bar_len = 0
        self._reverse_direction = False

    def _complete_len(self, progress):
        return int(self._BAR_MAX_LEN * progress / 100)

    def _incomplete_len(self, progress):
        return self._BAR_MAX_LEN - self._complete_len(progress)

    def _print(self, progress=None):
        if progress == 100:
            sys.stdout.write('\r[{}] done\r\n'.format('█' * self._BAR_MAX_LEN))
        else:
            if self._endless:
                tail = self._BAR_MAX_LEN - self._bar_len - self._position
                sys.stdout.write(
                    '\r[{}{}{}] ...'.format(' ' * self._position,
                                            '█' * self._bar_len, ' ' * tail))
            else:
                sys.stdout.write(
                    '\r[{}{}] {}%'.format('█' * self._complete_len(progress),
                                          ' ' * self._incomplete_len(progress),
                                          progress))

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
                if self._position == 0 and self._bar_len < self._ENDLESS_BAR_LEN:
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
    def __init__(self, endless=False):
        super().__init__(target=self._run)
        self._bar = ProgressBar(endless)
        self._progress = None if endless else 0
        super().start()

    def _run(self):
        while True:
            self._bar.update(self._progress)
            if self._progress == 100:
                break
            time.sleep(0.2)

    def update(self, progress):
        self._progress = progress


class DfuCommandHandler(object):
    def __init__(self):
        self._dfu = Stm32UartDfu('/dev/ttyUSB0')

    def get_id(self, args):
        print('MCU ID: 0x{}'.format(self._dfu.get_id().hex()))

    def run(self, args):
        print('MCU will be running from {}.'.format(args.address))

        self._dfu.go(int(args.address, 0))

    def erase(self, args):
        if args.memory_map is not None:
            with open(args.memory_map, 'r') as map_file:
                mem_map = json.load(map_file)
        else:
            mem_map = None

        if args.size is not None:
            print('Erasing {} bytes from {}...'.format(args.size, args.address))
        else:
            print('Erasing whole memory...')

        bar_thread = ProgressBarThread(endless=True)
        self._dfu.erase(args.address, args.size, mem_map, bar_thread.update)
        bar_thread.join()

    def dump(self, args):
        print('Dumping {} bytes from {}...'.format(args.size, args.address))

        bar_thread = ProgressBarThread()

        with open(args.file, 'wb') as dump:
            dump.write(self._dfu.read(int(args.address, 0), int(args.size, 0),
                                      bar_thread.update))
        bar_thread.join()

    def load(self, args):
        with open(args.file, 'rb') as firmware_file:
            firmware = firmware_file.read()

        if args.erase:
            if args.memory_map is not None:
                with open(args.memory_map, 'r') as map_file:
                    mem_map = json.load(map_file)
                print('Erasing {} bytes from {}...'.format(len(firmware),
                                                           args.address))
                erase_size = hex(len(firmware))
            else:
                print('Erasing whole memory...')
                mem_map = None
                erase_size = None

            bar_thread = ProgressBarThread(endless=True)
            self._dfu.erase(args.address, erase_size, mem_map,
                            bar_thread.update)
            bar_thread.join()

        print('Loading {} ({} bytes) at {}'.format(args.file, len(firmware),
                                                   args.address))

        bar_thread = ProgressBarThread()
        self._dfu.write(int(args.address, 0), firmware, bar_thread.update)
        bar_thread.join()

        print('Validating firmware...')

        bar_thread = ProgressBarThread()
        dump = self._dfu.read(int(args.address, 0), len(firmware),
                              bar_thread.update)
        bar_thread.join()

        if zlib.crc32(firmware) != zlib.crc32(dump):
            print('Error: checksum mismatch!')
        else:
            print('Success: firmware is valid.')

        if args.run:
            print('MCU will be running from {}.'.format(args.address))
            self._dfu.go(int(args.address, 0))


if __name__ == '__main__':
    dfu_handler = DfuCommandHandler()

    __ARGS_HELP = {
        'address': 'Memory address for ',
        'size': 'Required size of memory to be ',
        'memmap': 'Json file, containing memory structure. Format: [{"address": "value", "size": "value"}, ...]',
        'run': 'Run program after loading.',
        'erase': 'Erase memory enough to store firmware (whole memory if no memory map).'
    }

    arg_parser = argparse.ArgumentParser(description='Stm32 uart dfu utility.')
    commands = arg_parser.add_subparsers()

    load_command = commands.add_parser('load')
    load_command.add_argument('-a', '--address', default='0x8000000',
                              help=__ARGS_HELP[
                                       'address'] + 'loading binary file.')
    load_command.add_argument('-e', '--erase', action='store_true',
                              help=__ARGS_HELP['erase'])
    load_command.add_argument('-f', '--file', help='Binary firmware file.')
    load_command.add_argument('-m', '--memory-map', default=None,
                              help=__ARGS_HELP['memmap'])
    load_command.add_argument('-r', '--run', action='store_true',
                              help=__ARGS_HELP['run'])
    load_command.set_defaults(func=dfu_handler.load)

    erase_command = commands.add_parser('erase')
    erase_command.add_argument('-a', '--address', default='0x8000000',
                               help=__ARGS_HELP['address'] + 'erasing.')
    erase_command.add_argument('-m', '--memory-map', default=None,
                               help=__ARGS_HELP['memmap'])
    erase_command.add_argument('-s', '--size', default=None,
                               help=__ARGS_HELP['size'] + 'erased.')
    erase_command.set_defaults(func=dfu_handler.erase)

    dump_command = commands.add_parser('dump')
    dump_command.add_argument('-a', '--address', default='0x8000000',
                              help=__ARGS_HELP['address'] + 'dump.')
    dump_command.add_argument('-s', '--size', default=None,
                              help=__ARGS_HELP['size'] + 'dumped.')
    dump_command.add_argument('-f', '--file',
                              help='Specify file for memory dump.')
    dump_command.set_defaults(func=dfu_handler.dump)

    get_id_command = commands.add_parser('id')
    get_id_command.set_defaults(func=dfu_handler.get_id)

    run_command = commands.add_parser('run')
    run_command.add_argument('-a', '--address', default='0x8000000',
                             help=__ARGS_HELP['address'] + 'run.')
    run_command.set_defaults(func=dfu_handler.run)

    args = arg_parser.parse_args()
    args.func(args)
