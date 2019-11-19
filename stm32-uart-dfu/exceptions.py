from serial import SerialException


class DfuException(Exception):
    pass


class DfuAcknowledgeException(DfuException):
    """Dfu exception class for any acknowledgement issues."""

    def __init__(self, response: bytes):
        super().__init__(f'Acknowledge error (dfu response: {response}')


class DfuSerialIOException(DfuException, SerialException):
    """
    Dfu exception for serial io issues
    like tried to write n bytes, m<n written instead.
    """

    def __init__(self, expected: int, actual: int):
        super().__init__(
            f'Serial IO error: tried to transfer {expected}, {actual} done.')
