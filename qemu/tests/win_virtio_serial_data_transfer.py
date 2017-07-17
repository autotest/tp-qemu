import os
import time
import logging

from autotest.client import utils
from autotest.client.shared import error

from virttest import data_dir
from virttest import utils_misc
from virttest import utils_test
from virttest import qemu_virtio_port


VioSerial = qemu_virtio_port.VirtioSerial


class WinSerialTransferTest(object):

    def __init__(self, test, params, env):
        self.event = 'initilize'
        self.env = env
        self.test = test
        self.params = params
        self.vm = self._get_vm(params)

    def __enter__(self):
        """setup drive verifier before start test"""
        utils_test.qemu.setup_win_driver_verifier(
            'vioser.sys', self.vm, 720)
        self.install_required_scripts()
        return self

    def __exit__(self, *args):
        """ clean guest environment after test"""
        utils_test.qemu.clear_win_driver_verifier(
            'vioser.sys', self.vm, 720)
        self.uninstall_required_scripts()

    def _get_vm(self, params):
        """ get target test VM object from env"""
        vm = self.env.get_vm(params["main_vm"])
        vm.verify_alive()
        return vm

    def get_port_by_name(self, port_name):
        """
        get target serialport, if not set target port in
        params return first one

        :param port_name: serial port name
        return: VirtioSerial object
        """
        for port in self.vm.virtio_ports:
            if not isinstance(port, VioSerial):
                continue
            if not port_name:
                return port
            elif port.name == port_name:
                return port
        else:
            raise error.TestError("No eligible virtio serial port found")

    @error.context_aware
    def transfer_data(self, data_file):
        """
        key function to transfer data from host to gest via
        virtio serial port

        :param data_file: file path in host want to transfer it to guest
        """
        send_cmd, receive_cmd = self.generate_send_receive_cmds(data_file)
        error.context("Transfer file '%s' to guest" % data_file, logging.info)
        args = (receive_cmd, data_file)
        guest_receive = utils.InterruptedThread(self.receive_data, args)
        guest_receive.start()
        utils.system(send_cmd, timeout=30)
        self.event = 'sent'
        guest_receive.join(timeout=120)
        self.event = 'done'

    def generate_send_receive_cmds(self, data_file):
        """Gennerate send and receive shell commands by params"""
        deps_dir = data_dir.get_deps_dir("win_serial")
        send_script = self.params.get("host_send_script",
                                      "serial-host-send.py")
        send_script = os.path.join(deps_dir, send_script)
        virtio_port = self.get_port_by_name(self.params.get("target_port"))
        serial_send_cmd = " ".join(
            ["python", send_script, virtio_port.hostfile, data_file])
        receive_script = self.params.get(
            "guest_receive_script",
            "VirtIoChannel_guest_receive.py")
        receive_script = "c:\\%s" % receive_script
        serial_receive_cmd = " ".join(
            ["python", receive_script, virtio_port.name])
        return (serial_send_cmd, serial_receive_cmd)

    @error.context_aware
    def receive_data(self, serial_receive_cmd, data_file):
        """ start receive data file process in guest """
        error.context("Verify transfered data content", logging.info)
        session = self._get_session()
        try:
            output = session.cmd_output(serial_receive_cmd, timeout=30)
            ori_data = file(data_file, "r").read()
            if ori_data.strip() != output.strip():
                err = ("Data lost during transfer. Origin"
                       "data is:\n%s Guest receive data:\n%s" % (
                        ori_data, output))
                raise error.TestFail(err)
            self.event = 'received'
        finally:
            data_file = "c:\\%s" % os.path.basename(data_file)
            session.cmd("del /F %s" % data_file, ignore_all_errors=True)
            session.close()

    def _get_session(self):
        """ return guest shell session"""
        self.vm.verify_alive()
        login_timeout = int(self.params.get("login_timeout", 360))
        return self.vm.wait_for_login(timeout=login_timeout)

    @error.context_aware
    def install_required_scripts(self):
        """
        install required script into guest which will use to
        receive data from host
        """
        deps_dir = data_dir.get_deps_dir("win_serial")
        error.context("Copy test scripts to guest.", logging.info)
        guest_scripts = self.params["guest_scripts"]
        for script in guest_scripts.split(";"):
            src_file = os.path.join(deps_dir, script)
            self.vm.copy_files_to(src_file, "c:\\", timeout=60)
        self.event = "prepare"

    @error.context_aware
    def uninstall_required_scripts(self):
        """ cleanup installed script in guest """
        guest_scripts = self.params["guest_scripts"]
        error.context("Copy test scripts to guest.", logging.info)
        session = self._get_session()
        try:
            for script in guest_scripts.split(";"):
                script = "c:\\%s" % script
                session.cmd("del /F %s" % script, timeout=60)
            self.event = "cleanup"
        except Exception:
            logging.warn("Failed to remove %s" % guest_scripts)
        finally:
            session.close()


def run(test, params, env):
    """
    QEMU 'Windows virtio-serial data transfer' test

    1) Start guest with one virtio-serial-pci and two virtio-serial-port.
    2) Make sure vioser.sys verifier enabled in guest.
    3) Transfering data from host to guest via virtio-serial-port in a loop.
    4) Reboot guest.
    5) Repeat step 3.
    6) Reboot guest by system_reset qmp command.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def logtime_transfer(win_serial_test, data_file, repeat):
        """
        Run data transfer from host to guest in loop
        """
        for count in xrange(1, repeat + 1):
            logging.info("transfer repeat %d times" % count)
            win_serial_test.transfer_data(data_file)

    transfer_timeout = int(params.get("transfer_timeout", 900))
    repeat = int(params.get("repeat_times", 1))
    deps_dir = data_dir.get_deps_dir("win_serial")
    send_script = params.get("host_send_script", "serial-host-send.py")
    data_file = os.path.join(deps_dir, send_script)
    interrupt = params.get("interrupt", "yes") == "yes"
    with WinSerialTransferTest(test, params, env) as win_serial_test:
        args = (win_serial_test, data_file, repeat)
        transfer_thread = utils.InterruptedThread(logtime_transfer, args)
        transfer_thread.start()
        start_transfer = utils_misc.wait_for(
            lambda: win_serial_test.event == "sent",
            timeout=transfer_timeout)
        if not start_transfer:
            raise error.TestFail("No transimiation start "
                                 "in last '%s' seconds" % transfer_timeout)
        if interrupt:
            sub_step = params.get("sub_step", "reboot")
            getattr(win_serial_test.vm, sub_step)()
            if sub_step == "shutdown":
                win_serial_test.vm.create()
        elif params.get("sub_step") == "pause_resume":
            win_serial_test.vm.pause()
            pause_time = float(params.get("pause_time", 300))
            time.sleep(pause_time)
            win_serial_test.vm.resume()
        transfer_thread.join(timeout=10, suppress_exception=interrupt)
        logtime_transfer(*args)
        win_serial_test.vm.system_reset()
