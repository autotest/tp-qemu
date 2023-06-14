import logging
import os
import re
import time

from avocado.utils import process
from virttest import data_dir, error_context, qemu_virtio_port, utils_misc

from provider import win_driver_utils

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def get_abstract_address(hostfile):
    """
    Only for unix socket

    :param hostfile: the unix socket path in command
    :return: Abstract hostfile address for unix socket
    """
    find_cmd = "cat /proc/net/unix | grep '%s'" % hostfile
    abstract_hostfile = process.getoutput(find_cmd).strip().split(" ")[-1]
    return abstract_hostfile


@error_context.context_aware
def copy_scripts(guest_scripts, guest_path, vm):
    """
    Copy data transfer scripts to guest

    :param guest_scripts: guest scripts name, separated by ';'
    :param guest_path: guest path to locate the scripts
    :param vm: VM Object
    """
    error_context.context("Copy test scripts to guest.", LOG_JOB.info)
    for script in guest_scripts.split(";"):
        link = os.path.join(data_dir.get_root_dir(), "shared", "deps", "serial", script)
        vm.copy_files_to(link, guest_path, timeout=60)


@error_context.context_aware
def get_virtio_port_property(vm, port_name):
    """
    Get port type and port hostfile of the given port name
    :param vm: VM object
    :param port_name: the port name to be processed
    :return: port type and port hostfile
    """
    chardev_info = vm.monitor.human_monitor_cmd("info chardev")
    for port in vm.virtio_ports:
        if isinstance(port, qemu_virtio_port.VirtioSerial):
            if port.name == port_name:
                hostfile = port.hostfile
                # support abstract namespace Unix domain sockets
                if port.port_type == "unix_socket":
                    char_info = [m for m in chardev_info.split("\n") if hostfile in m][
                        0
                    ]
                    if "abstract=on" in char_info:
                        hostfile = get_abstract_address(hostfile)
                elif port.port_type in ("tcp_socket", "udp"):
                    hostfile = "%s:%s" % (port.hostfile[0], port.hostfile[1])
                elif port.port_type == "pty":
                    hostfile = re.findall(
                        "%s: filename=pty:(/dev/pts/\\d)?" % port_name, chardev_info
                    )[0]
                return port.port_type, hostfile


@error_context.context_aware
def get_command_options(sender="host", file_size=0):
    """
    Get the options of host and guest command, per different sender

    :param sender: who send data file
    :param file_size: the size of the file to be sent
    :return: host file size, guest file size, host action, guest action
    """
    if sender == "host":
        return file_size, 0, "send", "receive"
    elif sender == "guest":
        return 0, file_size, "receive", "send"
    else:
        return file_size, file_size, "both", "both"


@error_context.context_aware
def generate_data_file(dir_name, file_size=0, session=None):
    """
    Generate data file by dd command, on host or guest, depends on
    if session is provided

    :param dir_name: where to create the file
    :param file_size: the size of the file to be created
    :param session: guest session if have one, perform on host if None
    :return: the full file path
    """
    data_file = os.path.join(dir_name, "tmp-%s" % utils_misc.generate_random_string(8))
    cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (data_file, int(file_size))
    if not session:
        error_context.context("Creating %dMB file on host" % file_size, LOG_JOB.info)
        process.run(cmd)
    else:
        error_context.context("Creating %dMB file on guest" % file_size, LOG_JOB.info)
        session.cmd(cmd, timeout=600)
    return data_file


@error_context.context_aware
def _transfer_data(session, host_cmd, guest_cmd, timeout, sender):
    """
    Send transfer data command and check result via output

    :param session: guest session
    :param host_cmd: host script command
    :param guest_cmd: guest script command
    :param timeout: timeout for data transfer
    :param sender: who send data file
    :return: True if pass, False and error message if check fail
    """
    md5_host = "1"
    md5_guest = "2"

    def check_output(output):
        if not output:
            err = "The script output is empty, not terminate as expected"
            return False, err
        md5_re = "md5_sum = (\\w{32})"
        try:
            md5 = re.findall(md5_re, output)[0]
        except Exception:
            err = "Fail to get md5, script may fail."
            err += " Script output:\n%s" % output
            return False, err
        return True, md5

    try:
        kwargs = {"cmd": host_cmd, "shell": True, "timeout": timeout}
        error_context.context("Send host command: %s" % host_cmd, LOG_JOB.info)
        host_thread = utils_misc.InterruptedThread(process.getoutput, kwargs=kwargs)
        host_thread.daemon = True
        host_thread.start()
        time.sleep(1)
        g_output = session.cmd_output(guest_cmd, timeout=timeout)
        result = check_output(g_output)
        if result[0] is False:
            return result
        else:
            md5_guest = result[1]
    finally:
        if host_thread:
            output = host_thread.join(10)
            result = check_output(output)
            if result[0] is False:
                return result
            else:
                md5_host = result[1]
        if md5_host != md5_guest:
            err = "Data lost during file transfer. Md5 miss match."
            err += " Guest script output:\n %s" % g_output
            err += " Host script output:\n%s" % output
            return False, err
    return True


@error_context.context_aware
def transfer_data(
    params,
    vm,
    host_file_name=None,
    guest_file_name=None,
    sender="both",
    clean_file=True,
):
    """
    Transfer data file between guest and host, and check result via output;
    Generate random file first if not provided

    :param params: Params Object
    :param vm: VM Object
    :param host_file_name: Host file name to be transferred
    :param guest_file_name: Guest file name to be transferred
    :param sender: Who send the data file
    :param clean_file: Whether clean the data file transferred
    :return: True if pass, False and error message if check fail
    """

    file_size = int(params.get("filesize", 10))
    host_dir = data_dir.get_tmp_dir()
    guest_dir = params.get("tmp_dir", "/var/tmp/")
    if not host_file_name:
        host_file_name = generate_data_file(host_dir, file_size)
    if not guest_file_name:
        session = vm.wait_for_login()
        guest_file_name = generate_data_file(guest_dir, file_size, session)
        session.close()
    if sender != "both":
        return transfer_data_exec(
            params, vm, host_file_name, guest_file_name, file_size, sender, clean_file
        )
    else:
        host_res = transfer_data_exec(
            params,
            vm,
            host_file_name,
            guest_file_name,
            file_size,
            "host",
            clean_file=False,
        )
        if not host_res:
            return host_res
        guest_res = transfer_data_exec(
            params, vm, host_file_name, guest_file_name, file_size, "guest", clean_file
        )
        return guest_res


@error_context.context_aware
def transfer_data_exec(
    params,
    vm,
    host_file_name=None,
    guest_file_name=None,
    file_size=0,
    sender="host",
    clean_file=True,
):
    """
    Transfer data file from guest to host or vise versa, and return result;

    :param params: Params Object
    :param vm: VM Object
    :param host_file_name: Host file name to be transferred
    :param guest_file_name: Guest file name to be transferred
    :param file_size: the file_size to be created if files do not exist
    :param sender: Who send the data file
    :param clean_file: Whether clean the data file transferred
    :return: True if pass, False and error message if check fail

    """
    session = vm.wait_for_login()
    os_type = params["os_type"]
    try:
        guest_path = params.get("guest_script_folder", "C:\\")
        guest_scripts = params.get(
            "guest_scripts", "VirtIoChannel_guest_send_receive.py"
        )
        copy_scripts(guest_scripts, guest_path, vm)
        port_name = params["file_transfer_serial_port"]
        port_type, port_path = get_virtio_port_property(vm, port_name)
        transfer_timeout = int(params.get("transfer_timeout", 720))
        host_dir = data_dir.get_tmp_dir()
        guest_dir = params.get("tmp_dir", "/var/tmp/")
        host_file_size, guest_file_size, host_action, guest_action = (
            get_command_options(sender, file_size)
        )
        if not host_file_name:
            host_file_name = generate_data_file(host_dir, host_file_size)
        if not guest_file_name:
            guest_file_name = generate_data_file(guest_dir, guest_file_size, session)
        host_script = params.get("host_script", "serial_host_send_receive.py")
        host_script = os.path.join(
            data_dir.get_root_dir(), "shared", "deps", "serial", host_script
        )
        python_bin = "`command -v python python3 | head -1`"
        host_cmd = "%s %s -t %s -s %s -f %s -a %s" % (
            python_bin,
            host_script,
            port_type,
            port_path,
            host_file_name,
            host_action,
        )
        guest_script = os.path.join(guest_path, params["guest_script"])
        python_bin = params.get("python_bin", python_bin)
        guest_cmd = "%s %s -d %s -f %s -a %s" % (
            python_bin,
            guest_script,
            port_name,
            guest_file_name,
            guest_action,
        )
        result = _transfer_data(session, host_cmd, guest_cmd, transfer_timeout, sender)
    finally:
        if os_type == "windows":
            guest_file_name = guest_file_name.replace("/", "\\")
        if clean_file:
            clean_cmd = params["clean_cmd"]
            os.remove(host_file_name)
            session.cmd("%s %s" % (clean_cmd, guest_file_name))
        session.close()
    return result


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio serial guest file transfer.

    Steps:
    1) Boot up a VM with virtio serial device.
    2) Create a large file in guest or host(if needed).
    3) Copy this file between guest and host through virtio serial.
    4) Check if file transfers ended good by md5 value.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    sender = params["file_sender"]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    test.log.info("Transfer data from %s", sender)
    result = transfer_data(params, vm, sender=sender)
    if params.get("memory_leak_check", "no") == "yes":
        # for windows guest, disable/uninstall driver to get memory leak based on
        # driver verifier is enabled
        if params.get("os_type") == "windows":
            win_driver_utils.memory_leak_check(vm, test, params)
    vm.destroy()
    if result is not True:
        test.fail("Test failed. %s" % result[1])
