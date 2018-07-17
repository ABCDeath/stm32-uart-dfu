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
        checksum = 0xff - command
        command_sequence = [command, checksum]

        bytes_sent = self._port_handle.write(command_sequence)
        if bytes_sent != len(command_sequence):
            # TODO: use some exceptions
            pass

        self._receive_response()

    def get_id(self):
        self._send_command(self.__COMMAND['get id'])

        size = int.from_bytes(self._port_handle.read(1), 'little') + 1
        pid = self._port_handle.read(size)

        self._receive_response()

        return pid


if __name__ == '__main__':
    dfu = Stm32UartDfu('/dev/ttyUSB0')

    pid = dfu.get_id()

    print('mcu id: 0x{}'.format(pid.hex()))
