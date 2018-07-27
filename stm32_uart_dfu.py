import argparse
import sys
import time
from queue import Empty
from queue import Queue
from threading import Thread

import serial


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

    def _receive_response(self):
        response = self._port_handle.read(1)
        if len(response) == 0:
            print('read timeout')
        else:
            if response != self.__RESPONSE['ack']:
                print('dfu answered nack (0x{})'.format(response.hex()))
        return response

    def _uart_dfu_init(self):
        __INIT_SEQUENCE = [0x7f]

        bytes_sent = self._port_handle.write(__INIT_SEQUENCE)
        if bytes_sent != len(__INIT_SEQUENCE):
            # TODO: use some exceptions
            pass

        self._receive_response()

    def __init__(self, port):
        self._port_handle = serial.Serial(port=port,
                                          baudrate=self.__DEFAULT_PARAMETERS[
                                              'baudrate'],
                                          parity=self.__DEFAULT_PARAMETERS[
                                              'parity'],
                                          timeout=self.__DEFAULT_PARAMETERS[
                                              'timeout'])
        if not self._port_handle.isOpen():
            print('Can not open serial port.')

        self._uart_dfu_init()

    def __delete__(self):
        if self._port_handle.isOpen():
            self._port_handle.close()

    def _send_command(self, command):
        command_sequence = [command, self._checksum(command)]

        for retry in range(0, self.__RETRY_MAX_NUM):
            bytes_sent = self._port_handle.write(command_sequence)
            if bytes_sent != len(command_sequence):
                # TODO: use some exceptions
                pass

            if self._receive_response() == self.__RESPONSE['ack']:
                break

            self._port_handle.flushInput()
            self._port_handle.flushOutput()

    def _set_address(self, address):
        self._port_handle.write(address.to_bytes(4, 'big'))
        checksum = self._checksum(address.to_bytes(4, 'big'))
        self._port_handle.write(checksum.to_bytes(1, 'big'))
        self._receive_response()

    def get_id(self):
        self._send_command(self.__COMMAND['get id'])

        size = int.from_bytes(self._port_handle.read(1), 'little') + 1
        pid = self._port_handle.read(size)

        self._receive_response()

        return pid

    def get_version(self):
        self._send_command(self.__COMMAND['get version'])

        size = int.from_bytes(self._port_handle.read(1), 'little')

        version = self._port_handle.read(1)
        commands = self._port_handle.read(size)

        return (version, commands)

    def get_version_extended(self):
        self._send_command(self.__COMMAND['get version and protection status'])

        version = self._port_handle.read(1)
        read_protection_status = self._port_handle.read(2)

        return (version, read_protection_status)

    def read(self, address, size, progress=None):
        size_remain = size
        data = bytearray()

        while size_remain > 0:
            progress.queue.clear()
            progress.put(int(100 * (size - size_remain) / size))

            part_size = self.__RW_MAX_SIZE \
                if size_remain > self.__RW_MAX_SIZE else size_remain
            offset = address + size - size_remain

            self._send_command(self.__COMMAND['read memory'])
            self._set_address(offset)

            self._port_handle.write(
                [part_size - 1, self._checksum(part_size - 1)])
            self._receive_response()

            chunk = self._port_handle.read(part_size)
            # TODO: check if chunk length < part_size
            data.extend(bytearray(chunk))

            size_remain -= part_size

        progress.put(100)

        return data

    def go(self, address):
        self._send_command(self.__COMMAND['go'])
        self._set_address(address)

    def write(self, address, data, progress=None):
        size_remain = len(data)

        while size_remain > 0:
            progress.queue.clear()
            progress.put(int(100 * (len(data) - size_remain) / len(data)))

            part_size = self.__RW_MAX_SIZE \
                if size_remain > self.__RW_MAX_SIZE else size_remain
            offset = address + len(data) - size_remain

            self._send_command(self.__COMMAND['write memory'])
            self._set_address(offset)

            chunk = data[offset - address:offset - address + part_size]
            checksum = 0xff & ((part_size - 1) ^ self._checksum(chunk))
            self._port_handle.write((part_size - 1).to_bytes(1, 'big'))
            self._port_handle.write(chunk)
            self._port_handle.write(checksum.to_bytes(1, 'big'))
            self._receive_response()

            size_remain -= part_size

        progress.put(100)

    def erase(self, address, size=None, progress=None):
        self._send_command(self.__COMMAND['extended erase'])

        if size is None:
            command_parameters = [0xff, 0xff, 0]
            command_parameters.append(self._checksum(command_parameters))

            self._port_handle.write(command_parameters)

            port_settings = self._port_handle.getSettingsDict()
            port_settings['timeout'] = None
            self._port_handle.applySettingsDict(port_settings)

            self._receive_response()

            port_settings['timeout'] = self.__DEFAULT_PARAMETERS['timeout']
            self._port_handle.applySettingsDict(port_settings)

            # FIXME: without this byte every command is nacked
            temp = 1
            self._port_handle.write(temp.to_bytes(1, 'big'))
            self._port_handle.read()
        else:
            raise NotImplementedError

        progress.put(100)


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
        super().__init__()
        self._bar = ProgressBar(endless)
        self._progress_queue = Queue()
        self._thread = Thread(target=self._run)
        self._thread.start()

    def _run(self):
        while True:
            try:
                progress = self._progress_queue.get_nowait() \
                    if self._bar.is_endless() else self._progress_queue.get()
            except Empty:
                progress = None

            self._bar.update(progress)
            time.sleep(0.2)
            if progress == 100:
                break

    def get_progress_queue(self):
        return self._progress_queue


if __name__ == '__main__':
    dfu = Stm32UartDfu('/dev/ttyUSB0')

    arg_parser = argparse.ArgumentParser(description='Stm32 uart dfu utility.')
    arg_parser.add_argument('-a', '--address', default='0x8000000')
    arg_parser.add_argument('-f', '--file')
    arg_parser.add_argument('-s', '--size', default=None)
    arg_action = arg_parser.add_mutually_exclusive_group()
    arg_action.add_argument('-e', '--erase', action='store_true')
    arg_action.add_argument('-d', '--dump', action='store_true')
    arg_action.add_argument('-l', '--load', action='store_true')
    arg_action.add_argument('--mcu-id', action='store_true')

    args = arg_parser.parse_args()

    if args.mcu_id:
        print('mcu id: 0x{}'.format(dfu.get_id().hex()))

    if args.erase:
        if args.size is not None:
            print('erasing {} bytes from {}...'.format(args.size, args.address))
        else:
            print('erasing whole memory ...')

        bar_thread = ProgressBarThread(endless=True)

        dfu.erase(args.address, args.size, bar_thread.get_progress_queue())

    if args.dump:
        print('dumping {} bytes from {}...'.format(args.size, args.address))

        bar_thread = ProgressBarThread()

        file = open(args.file, 'wb')
        file.write(dfu.read(int(args.address, 0), int(args.size, 0),
                            bar_thread.get_progress_queue()))
        file.close()

    if args.load:
        file = open(args.file, 'rb')
        firmware = file.read()
        file.close()

        # TODO: erase only space enough for firmware size
        print('erasing whole memory ...')

        bar_thread = ProgressBarThread(endless=True)

        dfu.erase(args.address, None, bar_thread.get_progress_queue())

        # FIXME: somehow wait for the progressbar 'done'
        time.sleep(1)

        print('loading {} ({} bytes) at {}'.format(args.file, len(firmware),
                                                   args.address))

        bar_thread = ProgressBarThread()

        dfu.write(int(args.address, 0), firmware,
                  bar_thread.get_progress_queue())
