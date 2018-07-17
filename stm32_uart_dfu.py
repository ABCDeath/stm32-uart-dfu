import serial


__DFU_RESPONSE_SIZE = 1

__DFU_RESPONSE = {
    'ack': 0x79.to_bytes(length=1, byteorder='little'),
    'nack': 0x7f.to_bytes(length=1, byteorder='little')
}

__DFU_COMMAND = {
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

def uart_dfu_init(serial_port):
    __DFU_INIT_SEQUENCE = [0x7f]

    bytes_sent = serial_port.write(__DFU_INIT_SEQUENCE)
    if bytes_sent != len(__DFU_INIT_SEQUENCE):
        # TODO: use some exceptions
        pass

    receive_response(serial_port)


def receive_response(serial_port):
    response = serial_port.read(1)
    if len(response) == 0:
        print('read timeout')
    else:
        if response != __DFU_RESPONSE['ack']:
            print('dfu answered nack')
    return response


def send_command(serial_port, command):
    checksum = 0xff - command
    command_sequence = [command, checksum]

    bytes_sent = serial_port.write(command_sequence)
    if bytes_sent != len(command_sequence):
        # TODO: use some exceptions
        pass

    receive_response(serial_port)


def get_id(serial_port):
    send_command(serial_port, __DFU_COMMAND['get id'])

    size = int.from_bytes(serial_port.read(1), 'little') + 1
    pid = serial_port.read(size)

    receive_response(serial_port)

    return pid


if __name__ == '__main__':
    serial_port = serial.Serial(port='/dev/ttyUSB0', baudrate=115200,
                                parity='E', timeout=1)
    if not serial_port.is_open:
        print('Can not open serial port.')

    uart_dfu_init(serial_port)

    pid = get_id(serial_port)

    print('mcu id: 0x{}'.format(pid.hex()))

    serial_port.close()
