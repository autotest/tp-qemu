import os
import signal
import time

from avocado.utils import process
from virttest import data_dir, error_context

from qemu.tests.virtio_serial_file_transfer import (
    generate_data_file,
    get_command_options,
    transfer_data,
)


@error_context.context_aware
def run(test, params, env):
    """
    Test long time virtio serial guest file transfer.

    Steps:
    1) Boot up a VM with virtio serial device.
    2) Create a large file in guest or host(sender).
    3) In 'repeat_time',  repeatedly transfer the file between guest and host
    4) Kill the data transfer process
    5) Check guest running well, no crash

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    params["os_type"]
    sender = params["file_sender"]
    file_size = int(params.get("filesize", 100))
    continue_time = int(params.get("continue_transfer_time", 600))
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    host_dir = data_dir.get_tmp_dir()
    guest_dir = params.get("tmp_dir", "/var/tmp/")
    host_file_size, guest_file_size, _, _ = get_command_options(sender, file_size)
    host_file_name = generate_data_file(host_dir, host_file_size)
    guest_file_name = generate_data_file(guest_dir, guest_file_size, session)

    check_pid_cmd = 'ps aux | grep "%s"| grep -v "grep"'
    host_script = params["host_script"]
    guest_script = params["guest_script"]
    test.log.info("Transfer data from %s", sender)
    try:
        test_time = time.time() + continue_time
        while time.time() < test_time:
            transfer_data(params, vm, host_file_name, guest_file_name, sender, False)
        host_proc = process.getoutput(check_pid_cmd % host_script, shell=True)
        guest_proc = session.cmd_output(check_pid_cmd % guest_script)
        if host_proc:
            host_pid = host_proc.split()[1]
            test.log.info("Kill serial process on host")
            os.kill(int(host_pid), signal.SIGINT)
        if guest_proc:
            guest_pid = guest_proc.split()[1]
            test.log.info("Kill serial process on guest")
            session.cmd("kill -9 %s" % guest_pid)
    finally:
        clean_cmd = params["clean_cmd"]
        session.cmd("%s %s" % (clean_cmd, guest_file_name))
        os.remove(host_file_name)
        session.close()
        vm.verify_kernel_crash()
        vm.destroy()
