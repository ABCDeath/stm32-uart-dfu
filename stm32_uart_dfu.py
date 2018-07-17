import serial


if __name__ == '__main__':
    serial_port = serial.Serial(port='/dev/ttyUSB0', baudrate=115200,
                                parity='E', timeout=1)
    if not serial_port.is_open:
        print('Can not open serial port.')

    data = [0x7f]

    ret = serial_port.write(data)
    print('write: {} byte(s)'.format(ret))

    ret = serial_port.read()
    if len(ret) == 0:
        print('read timeout')
    else:
        print('read: 0x{}'.format(ret.hex()))

    serial_port.close()
