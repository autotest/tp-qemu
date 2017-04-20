import os
import logging
import subprocess

from avocado.utils import process

from autotest.client.shared import error

from virttest import data_dir
from virttest import qemu_virtio_port
from virttest import utils_misc


# This decorator makes the test function aware of context strings
@error.context_aware
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

    def get_virtio_port_host_file(vm, port_name):
        """
        Returns separated virtserialports
        :param vm: VM object
        :return: All virtserialports
        """
        for port in vm.virtio_ports:
            if isinstance(port, qemu_virtio_port.VirtioSerial):
                if port.name == port_name:
                    return port.hostfile

    def transfer_data(session, host_file_path, guest_file_path, n_time,
                      timeout):
        host_cmd = ["python", host_script_path, "-s", host_serial_path, "-f",
                    host_file_path, "-a", "both"]
        guest_cmd = "python %s -d %s -f %s -a both" % (guest_script_path,
                                                       port_name,
                                                       guest_file_path)
        for num in xrange(n_time):
            logging.info("Data transfer repeat %s/%s." % (num + 1, n_time))
            logging.debug("Running: %s" % " ".join(host_cmd))
            host_proc = subprocess.Popen(host_cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
            if host_proc.poll() != None:
                h_stdout, h_stderr = host_proc.communicate()
                h_status = host_proc.returncode
                err = "Can not run transfer command on host\n"
                err += ("return code is (%s), stdout:\n%s\n"
                        "stderr:\n%s" % (h_status, h_stdout, h_stderr))
                raise error.TestFail(err)
            g_status, g_output = session.cmd_status_output(guest_cmd,
                                                           timeout=timeout)
            if not utils_misc.wait_for(lambda: host_proc.poll() != None,
                                       timeout, step=1):
                err = "Can not finish data transfer on host"
                raise error.TestFail(err)
            h_stdout, h_stderr = host_proc.communicate()
            h_status = host_proc.returncode
            if g_status or h_status:
                err = "Error occurred during data transfer\n"
                err += "guest return code is (%s), output:\n%s" % (g_status,
                                                                   g_output)
                err += ("host return code is (%s), stdout:\n%s\n"
                        "stderr:\n%s" % (h_status, h_stdout, h_stderr))
                raise error.TestFail(err)
            session.cmd("del %s" % guest_file_path, timeout=timeout)

    dep_dir = data_dir.get_deps_dir("win_serial")
    timeout = int(params.get("login_timeout", 360))
    port_name = params["virtio_ports"].split()[-1]
    check_cmd = params.get("check_vioser_status_cmd",
                           "verifier /querysettings")
    verify_cmd = params.get("vioser_verify_cmd",
                            "verifier.exe /standard /driver vioser.sys")
    guest_scripts = params["guest_scripts"].split(";")
    guest_path = params.get("guest_script_folder", "C:\\")
    guest_script = params.get("guest_script",
                              "VirtIoChannel_guest_send_receive.py")
    host_script = params.get("host_script", "serial_host_send_receive.py")
    n_time = int(params.get("repeat_times", 20))
    test_timeout = timeout

    guest_script_path = "%s%s" % (guest_path, guest_script)
    host_script_path = os.path.join(dep_dir, host_script)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    host_serial_path = get_virtio_port_host_file(vm, port_name)
    session = vm.wait_for_login(timeout=timeout)

    error.context("Make sure vioser.sys verifier enabled in guest.",
                  logging.info)
    output = session.cmd(check_cmd, timeout=test_timeout)
    if "vioser.sys" not in output:
        session.cmd(verify_cmd, timeout=test_timeout, ok_status=[0, 2])
        session = vm.reboot(session=session, timeout=timeout)
        output = session.cmd(check_cmd, timeout=test_timeout)
        if "vioser.sys" not in output:
            error.TestError("Fail to veirfy vioser.sys driver.")

    error.context("Copy test scripts to guest.", logging.info)
    for script in guest_scripts:
        src_path = os.path.join(dep_dir, script)
        vm.copy_files_to(src_path, guest_path, timeout=test_timeout)

    host_file_path = os.path.join(data_dir.get_tmp_dir(), "10M")
    process.run("dd if=/dev/urandom of=%s bs=1M count=10" % host_file_path,
                timeout=test_timeout)
    guest_file_path = "%srecv.dat" % guest_path

    error.context("Transfer data between host and guest.", logging.info)
    transfer_data(session, host_file_path, guest_file_path, n_time,
                  test_timeout)

    error.context("Reboot guest.", logging.info)
    session = vm.reboot(session=session, timeout=timeout)

    error.context("Transfer data between host and guest.", logging.info)
    transfer_data(session, host_file_path, guest_file_path, n_time,
                  test_timeout)

    error.context("Reboot guest by system_reset qmp command.", logging.info)
    session = vm.reboot(session=session, method="system_reset",
                        timeout=timeout)
    if session:
        session.close()
