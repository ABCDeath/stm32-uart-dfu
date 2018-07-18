import serial


class Stm32UartDfu:
    __DEFAULT_PARAMETERS = {
        'baudrate': 115200,
        'parity': 'E',
        'timeout': 1  # seconds
    }

    __RESPONSE_SIZE = 1

    __RESPONSE = {
        'ack': 0x79.to_bytes(length=1, byteorder='little'),
        'nack': 0x7f.to_bytes(length=1, byteorder='little')
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
                print('dfu answered nack')
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

        bytes_sent = self._port_handle.write(command_sequence)
        if bytes_sent != len(command_sequence):
            # TODO: use some exceptions
            pass

        self._receive_response()

    def _set_address(self, address):
        self._port_handle.write(address.to_bytes(4, 'big'))
        self._port_handle.write(self._checksum(address.to_bytes(4, 'big')))
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

    def read(self, address, size):
        __READ_CYCLE_MAX_SIZE = 256
        size_remain = size
        data = bytearray()

        while size_remain > 0:
            part_size = __READ_CYCLE_MAX_SIZE if size - size_remain > __READ_CYCLE_MAX_SIZE else size - size_remain
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

        return data

    def go(self, address):
        self._send_command(self.__COMMAND['go'])
        self._set_address(address)

    def write(self, address, data):
        __WRITE_CYCLE_MAX_SIZE = 256
        size_remain = len(data)

        while size_remain > 0:
            part_size = __WRITE_CYCLE_MAX_SIZE if len(
                data) - size_remain > __WRITE_CYCLE_MAX_SIZE else len(
                data) - size_remain
            offset = address + len(data) - size_remain

            self._send_command(self.__COMMAND['write memory'])
            self._set_address(offset)

            chunk = data[offset - address:offset - address + part_size]
            checksum = part_size ^ self._checksum(chunk)
            self._port_handle.write([part_size - 1, chunk, checksum])
            self._receive_response()

            size_remain -= part_size

    def erase(self, address, size=0):
        self._send_command(self.__COMMAND['extended erase'])

        if size == 0:
            command_parameters = [0xff, 0xff, 0]
            self._port_handle.write(
                [command_parameters, self._checksum(command_parameters)])

            port_settings = self._port_handle.getSettingsDict()
            port_settings['timeout'] = None
            self._port_handle.applySettingsDict(port_settings)

            self._receive_response()

            port_settings['timeout'] = self.__DEFAULT_PARAMETERS['timeout']
            self._port_handle.applySettingsDict(port_settings)
        else:
            raise NotImplementedError



if __name__ == '__main__':
    dfu = Stm32UartDfu('/dev/ttyUSB0')

