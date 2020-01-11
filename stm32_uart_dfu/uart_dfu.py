import argparse
import json
import time
import zlib
from threading import Thread
from typing import NoReturn

from .exceptions import DfuException
from .stm32uartdfu import Stm32UartDfu


class ProgressBar:
    _BAR_MAX_LEN = 40
    _ENDLESS_BAR_LEN = 20

    def __init__(self, endless: bool = False):
        self._endless = endless
        self._position = 0
        self._bar_len = 0
        self._reverse_direction = False

    def _complete_len(self, progress: int) -> int:
        return int(self._BAR_MAX_LEN * progress / 100)

    def _incomplete_len(self, progress: int) -> int:
        return self._BAR_MAX_LEN - self._complete_len(progress)

    def _print(self, progress: int = None) -> NoReturn:
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

    def is_endless(self) -> bool:
        return self._endless

    def update(self, progress: int = None) -> NoReturn:
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

    def __init__(self, endless: bool = False):
        super().__init__(target=self._run)
        self._bar = ProgressBar(endless)
        self._progress = None if endless else 0
        super().start()

    def _run(self) -> NoReturn:
        while True:
            self._bar.update(self._progress)
            if self._progress == 100 or self._progress == -1:
                break
            time.sleep(self._WAKE_PERIOD)

    def update(self, progress: int) -> NoReturn:
        self._progress = progress


class DfuCommandHandler:
    @staticmethod
    def _abort(bar_thread: ProgressBarThread = None) -> NoReturn:
        if bar_thread:
            bar_thread.update(-1)
            bar_thread.join()

        print('An Error occurred Reset MCU and try again.')

    @staticmethod
    def get_id(dfu: Stm32UartDfu, args: argparse.Namespace) -> NoReturn:
        print('MCU ID: 0x{}'.format(dfu.id.hex()))

    @staticmethod
    def run(dfu: Stm32UartDfu, args: argparse.Namespace) -> NoReturn:
        print(f'MCU will be running from {args.address}.')

        dfu.go(int(args.address, 0))

    def erase(self, dfu: Stm32UartDfu, args: argparse.Namespace) -> NoReturn:
        if args.memory_map:
            with open(args.memory_map) as map_file:
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

    def dump(self, dfu: Stm32UartDfu, args: argparse.Namespace) -> NoReturn:
        print(f'Dumping {args.size} bytes from {args.address}...')

        bar_thread = ProgressBarThread()

        try:
            with open(args.file, 'wb') as dump:
                dump.write(
                    dfu.read(int(args.address, 0), int(args.size, 0),
                             bar_thread.update))
        except DfuException:
            self._abort(bar_thread)
            raise

        bar_thread.join()

    def load(self, dfu: Stm32UartDfu, args: argparse.Namespace) -> NoReturn:
        with open(args.file, 'rb') as firmware_file:
            firmware = firmware_file.read()

        if args.erase:
            if args.memory_map:
                with open(args.memory_map) as map_file:
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
