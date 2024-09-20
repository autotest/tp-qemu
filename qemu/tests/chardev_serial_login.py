import os
import re

from virttest import env_process, error_context, qemu_monitor, remote


@error_context.context_aware
def run(test, params, env):
    """
    Verify the login function of chardev-serial (RHEL only):
    1) Start guest with chardev-serial with backend
    2) for pty and file backend:
      2.1) open and close chardev
    3) for unix_socket and tcp_socket
      3.1) Login guest.
      3.2) move, create files inside guest
    4) Hot-unplug chardev which is in use, should fail.
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def check_guest():
        session.cmd("touch file.txt")  # pylint: disable=E0606
        session.cmd("mkdir -p tmp")
        session.cmd("command cp file.txt ./tmp/test.txt")

    serial_id = params.objects("serials")[-1]
    prompt = params.get("shell_prompt")
    if params["serial_type"] == "spapr-vty" and params["inactivity_watcher"] == "none":
        params["vga"] = "none"
    params["start_vm"] = "yes"
    for backend in ["tcp_socket", "unix_socket", "pty", "file"]:
        params["chardev_backend_%s" % serial_id] = backend
        env_process.preprocess(test, params, env)
        vm = env.get_vm(params["main_vm"])
        vm.wait_for_login()
        serial_device = vm.devices.get(serial_id)
        chardev_qid = serial_device.get_param("chardev")
        chardev_device = vm.devices.get_by_qid(chardev_qid)[0]
        if backend == "tcp_socket":
            session = remote.remote_login(
                client="nc",
                host=chardev_device.params["host"],
                port=chardev_device.params["port"],
                username="root",
                password="kvmautotest",
                prompt=prompt,
                timeout=240,
            )
            check_guest()
        elif backend == "unix_socket":
            session = vm.wait_for_serial_login()
            check_guest()
        elif backend == "pty":
            chardev_info = vm.monitor.human_monitor_cmd("info chardev")
            hostfile = re.findall(
                "%s: filename=pty:(/dev/pts/\\d)?" % "serial0", chardev_info
            )[0]
            if not hostfile:
                test.fail("Guest boot fail with pty backend.")
            fd_pty = os.open(hostfile, os.O_RDWR | os.O_NONBLOCK)
            os.close(fd_pty)
        elif backend == "file":
            filename = chardev_device.params["path"]
            f = open(filename, errors="ignore")
            if "Linux" not in f.read():
                f.close()
                test.fail("Guest boot fail with file backend.")
            f.close()
        try:
            vm.devices.simple_unplug(chardev_device, vm.monitor)
        except qemu_monitor.QMPCmdError as e:
            if "is busy" not in e.data["desc"]:
                test.fail(e.data["desc"])
        else:
            test.fail("Hot-unplug should fail.")
        vm.destroy()
