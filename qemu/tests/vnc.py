import logging
import random
import socket
import struct
import time

from virttest import error_context, utils_misc
from virttest.RFBDes import Des

LOG_JOB = logging.getLogger("avocado.test")


class VNC(object):
    """
    Simple VNC client which can only connect to and authenticate with
    vnc server.
    """

    def __init__(self, host="localhost", port="5900", rfb_version="3.8"):
        self.sock = socket.socket()
        self.sock.settimeout(5)
        self.sock.connect((host, int(port)))
        self.rfb_version = rfb_version

    def hand_shake(self, password=None):
        """
        Dealing with handshake message.
        """
        rfb_server_version = self.sock.recv(12)
        LOG_JOB.debug("VNC server rfb version: %s", rfb_server_version)
        LOG_JOB.debug("Handshake with rfb protocol version: %s", self.rfb_version)
        rfb_version = "RFB 00%s.00%s\n" % (
            self.rfb_version.split(".")[0],
            self.rfb_version.split(".")[1],
        )
        self.sock.send(rfb_version)
        if self.rfb_version != "3.3":
            rec = self.sock.recv(1)
            (auth,) = struct.unpack("!B", rec)
            if auth == 0:
                rec = self.sock.recv(4)
                (reason_len,) = struct.unpack("!I", rec)
                reason = self.sock.recv(reason_len)
                LOG_JOB.error("Connection failed: %s", reason)
                return False
            else:
                rec = self.sock.recv(auth)
                (auth_type,) = struct.unpack("!%sB" % auth, rec)
                LOG_JOB.debug("Server support '%s' security types", auth_type)
        else:
            rec = self.sock.recv(4)
            (auth_type,) = struct.unpack("!I", rec)
            LOG_JOB.debug("Server support %s security types", auth_type)

        if auth_type == 0:
            LOG_JOB.error("Invalid security types")
            return False
        elif auth_type == 1:
            if password is not None:
                LOG_JOB.error("Security types is None")
                return False
        elif auth_type == 2:
            LOG_JOB.debug("VNC Authentication")
            if self.rfb_version != "3.3":
                self.sock.send(struct.pack("!B", 2))
            rec = self.sock.recv(16)
            des = Des(password)
            p = des.crypt(rec)
            self.sock.send(p)
            # Security Result check phase
            rec = self.sock.recv(4)
            (status,) = struct.unpack("!I", rec)
            if status == 1:
                if self.rfb_version == "3.8":
                    rec = self.sock.recv(4)
                    (str_len,) = struct.unpack("!I", rec)
                    reason = self.sock.recv(str_len)
                    LOG_JOB.debug("Handshaking failed : %s", reason)
                return False
            elif status == 0:
                return True

    def initialize(self, shared_flag=0):
        """
        Dealing with VNC initial message.
        """
        (shared_flag,) = struct.pack("!B", shared_flag)
        self.sock.send(shared_flag)
        rec = self.sock.recv(24)
        (width, height, pixformat, name_len) = struct.unpack("!HH16sI", rec)
        (
            bits_per_pixel,
            depth,
            big_endian,
            true_color,
            red_max,
            green_max,
            blue_max,
            red_shift,
            green_shift,
            blue_shift,
        ) = struct.unpack("!BBBBHHHBBBxxx", pixformat)
        server_name = self.sock.recv(name_len)
        LOG_JOB.info("vnc server name: %s", server_name)

    def close(self):
        self.sock.close()


@error_context.context_aware
def run(test, params, env):
    """
    Base test for vnc, mainly focus on handshaking during vnc connection setup.
    This case check following point:
    1) VNC server support different rfb protocol version. Now it is 3.3, 3.7
       and 3.8.
    2) Connection could be setup with password enable.
    3) Change and __com.redhat_set_password monitor command could work.

    This case will do following step:
    1) Start VM with VNC password enable.
    2) Handshaking after vnc password set by change.
    3) Handshaking after vnc password set by __com.redhat_set_password.
    4) Handshaking again after vnc password timeout.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    port = vm.get_vnc_port()
    default_cmd = "__com.redhat_set_password protocol=vnc,"
    default_cmd += "password=%s,expiration=%s"
    change_passwd_cmd = params.get("change_passwd_cmd", default_cmd)
    rfb_version_list = params.get("rfb_version").strip().split()
    for rfb_version in rfb_version_list:
        error_context.base_context("Test with guest RFB version %s" % rfb_version)
        rand = random.SystemRandom()
        rand.seed()
        password = utils_misc.generate_random_string(rand.randint(1, 8))
        test.log.info("Set VNC password to: %s", password)
        timeout = rand.randint(10, 100)
        test.log.info("VNC password timeout is: %s", timeout)
        vm.monitor.send_args_cmd(change_passwd_cmd % (password, timeout))

        error_context.context(
            "Connect to VNC server after setting password" " to '%s'" % password
        )
        vnc = VNC(port=port, rfb_version=rfb_version)
        status = vnc.hand_shake(password)
        vnc.initialize()
        vnc.close()
        if not status:
            test.fail("VNC Authentication failed.")

        test.log.info("VNC Authentication pass")
        test.log.info("Waiting for vnc password timeout.")
        time.sleep(timeout + 5)
        error_context.context("Connect to VNC server after password expires")
        vnc = VNC(port=port, rfb_version=rfb_version)
        status = vnc.hand_shake(password)
        vnc.close()
        if status:
            # Should not handshake succeffully.
            test.fail(
                "VNC connected with Timeout password, The"
                " cmd of setting expire time doesn't work."
            )
