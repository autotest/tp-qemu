#!/usr/bin/python
#
# Copyright 2010 Red Hat, Inc. and/or its affiliates.
#
# Licensed to you under the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.  See the files README and
# LICENSE_GPL_v2 which accompany this distribution.
#

import os
import platform
import socket
import struct
import sys


class Message:
    PowerUp = 1
    PowerDown = 2
    Heartbeat = 3
    MachineName = 4
    GuestOs = 5
    IpAddresses = 6
    LastSessionMessage = 7
    UserInfo = 8
    NewApp = 9
    FlushApps = 10
    ClientIp = 11  # Obsolete
    SessionLock = 12
    SessionUnlock = 13
    SessionLogoff = 14
    SessionLogon = 15
    AgentCommand = 16  # Obsolete
    AgentUninstalled = 17  # A place holder.
    SessionStartup = 18
    SessionShutdown = 19


READ_HEADER = "III"
READ_HEADER_LEN = struct.calcsize(READ_HEADER)
WRITE_HEADER = "IIII"
WRITE_HEADER_LEN = struct.calcsize(WRITE_HEADER)


class VirtIoChannel:
    # Python on Windows 7 return 'Microsoft' rather than 'Windows' as documented.
    is_windows = (platform.system() == "Windows") or (platform.system() == "Microsoft")

    def __init__(self, vport_name):
        if self.is_windows:
            from windows_support import WinBufferedReadFile

            self._vport = WinBufferedReadFile(vport_name)
        else:
            self._vport = os.open(vport_name, os.O_RDWR)

    def read(self):
        size = self._read_header()
        if self.is_windows:
            rest = self._vport.read(size)
        else:
            rest = os.read(self._vport, size)
        # TODO: concat message? handle NULL terminated string?
        cmd = struct.unpack("%ds" % len(rest), rest)[0]
        return cmd

    def write(self, message, arg=""):
        if not isinstance(message, int):
            raise TypeError("1nd arg must be a known message type.")
        if not isinstance(arg, str):
            raise TypeError("2nd arg must be a string.")
        stream = self._pack_message(message, arg)
        if self.is_windows:
            self._vport.write(stream)
        else:
            os.write(self._vport, stream)

    def _read_header(self):
        if self.is_windows:
            hdr = self._vport.read(READ_HEADER_LEN)
        else:
            hdr = os.read(self._vport, (READ_HEADER_LEN))
        if hdr == "":
            return 0
        return socket.ntohl(struct.unpack(READ_HEADER, hdr)[2]) - READ_HEADER_LEN

    def _pack_message(self, message, arg):
        size = WRITE_HEADER_LEN + len(arg)
        stream = struct.pack(
            WRITE_HEADER + "%ds" % len(arg),
            socket.htonl(1),
            socket.htonl(3),
            socket.htonl(size),
            socket.htonl(message),
            arg,
        )
        return stream


def test(path):
    if (platform.system() == "Windows") or (platform.system() == "Microsoft"):
        vport_name = "\\\\.\\Global\\" + path
    else:
        vport_name = "/dev/virtio-ports/" + path
    vio = VirtIoChannel(vport_name)
    print(vio.read())


if __name__ == "__main__":
    # ************************************************************************
    # This scripts only used for transferring file from host to guest.
    # You need to run python serial-host-send.py in host.
    # The scripts need to use device name.
    # eg -device virtserialport,chardev=xxx,name=vport1,id=port2 in command,
    # then you need run python VirtIoChannel_guest_recieve.py vport1.
    # ************************************************************************

    test(sys.argv[1])
