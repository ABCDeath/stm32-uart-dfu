import argparse

from .uart_dfu import DfuCommandHandler
from .stm32uartdfu import Stm32UartDfu


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
