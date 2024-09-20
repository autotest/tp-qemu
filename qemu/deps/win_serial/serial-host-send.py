#!/usr/bin/python

import socket
import struct
import sys

WRITE_HEADER = "III"
WRITE_HEADER_LEN = struct.calcsize(WRITE_HEADER)
READ_HEADER = "IIII"
READ_HEADER_LEN = struct.calcsize(READ_HEADER)


def pack_message(arg):
    size = WRITE_HEADER_LEN + len(arg)
    stream = struct.pack(
        WRITE_HEADER + "%ds" % len(arg),
        socket.htonl(1),
        socket.htonl(3),
        socket.htonl(size),
        arg,
    )
    return stream


def main():
    ##Note:
    # Please run python VirtIOChannel.py open in the guest first.
    # Please run this script with unix socket device.
    # If you have -chardev socket,id=channel2,path=/tmp/helloworld2 in qemu
    # command, you can run python serial-host-send.py /tmp/helloworld2.
    # Please create a.txt in same folder with this script. Will transfer
    # this file's context to guest.

    vport = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    vport.connect(sys.argv[1])
    data_file = sys.argv[2]

    with open(data_file, "rb") as ff:
        arg = ff.read(65535)
    stream = pack_message(arg)
    vport.send(stream)


if __name__ == "__main__":
    main()
