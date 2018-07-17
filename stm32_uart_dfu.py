import serial


__DFU_RESPONSE = {
    'ack': 0x79.to_bytes(length=1, byteorder='little'),
    'nack': 0x7f.to_bytes(length=1, byteorder='little')
}

def uart_dfu_init(serial_port):
    __DFU_INIT_SEQUENCE = [0x7f]

    bytes_sent = serial_port.write(__DFU_INIT_SEQUENCE)
    if bytes_sent != len(__DFU_INIT_SEQUENCE):
        # TODO: use some exceptions
        pass

    response = serial_port.read(1)
    if len(response) == 0:
        print('read timeout')
    else:
        if response != __DFU_RESPONSE['ack']:
            print('dfu answered nack')


def send_command(serial_port, command):
    checksum = 0xff - command
    command_sequence = [command, checksum]

    bytes_sent = serial_port.write(command_sequence)
    if bytes_sent != len(command_sequence):
        # TODO: use some exceptions
        pass

    response = serial_port.read(1)
    if len(response) == 0:
        print('read timeout')
    else:
        if response != __DFU_RESPONSE['ack']:
            print('dfu answered nack')


if __name__ == '__main__':
    serial_port = serial.Serial(port='/dev/ttyUSB0', baudrate=115200,
                                parity='E', timeout=1)
    if not serial_port.is_open:
        print('Can not open serial port.')

    uart_dfu_init(serial_port)

    send_command(serial_port, 0x2)

    ret = serial_port.read(4)
    if len(ret) == 0:
        print('read timeout')
    else:
        print('read: {}'.format(ret))

    serial_port.close()
