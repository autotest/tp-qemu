import os
import re

from virttest import error_context, remote, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Verify the login guest with multi backends spapr-vty:
    1) Boot guest with multi spapr-vty with backend
    2) Modify the kernel cfg file to specify the backend
    3) For pty and file backend:
      3.1) Open and close chardev
    4) For unix_socket and tcp_socket:
      4.1) Login guest
      4.2) Create and delete files inside guest
    5) Migrate the vm and do login test
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    prompt = params.get("shell_prompt")
    create_delete_file = params["create_delete_file"]
    vm = env.get_vm(params["main_vm"])
    vm.wait_for_login()
    # do migration
    if params.get("sub_type") == "migration_all_type":
        mig_timeout = float(params.get("mig_timeout", "3600"))
        mig_protocol = params.get("migration_protocol", "tcp")
        vm.migrate(mig_timeout, mig_protocol, env=env)
        session = vm.wait_for_login()
    for serial_id in params.objects("serials"):
        if serial_id != "vs1" and serial_id != "vs9":
            # where 9th or larger number spapr-vty devices could not be used as serial
            # since the maximum available console/serial devices is 8 inside the guest,
            # i.e. from /dev/hvc0 to /dev/hvc7
            hvc_id = int(serial_id.replace("vs", "")) - 1
            kernel_params = "console=hvc%s,115200" % hvc_id
            utils_test.update_boot_option(vm, args_added=kernel_params)

        backend = params.object_params(serial_id)["chardev_backend"]
        serial_device = vm.devices.get(serial_id)
        chardev_qid = serial_device.get_param("chardev")
        chardev_device = vm.devices.get_by_qid(chardev_qid)[0]

        test.log.info("The currently tested backend is %s.", backend)
        if backend == "unix_socket":
            session = vm.wait_for_serial_login(timeout=60)
            session.cmd(create_delete_file)
            session.close()
        elif backend == "tcp_socket":
            session = remote.remote_login(
                client="nc",
                host=chardev_device.params["host"],
                port=chardev_device.params["port"],
                username=params["username"],
                password=params["password"],
                prompt=prompt,
                timeout=240,
            )
            session.cmd(create_delete_file)
            session.close()
        elif backend == "pty":
            chardev_info = vm.monitor.human_monitor_cmd("info chardev")
            hostfile = re.findall(
                "%s: filename=pty:(/dev/pts/\\d)?" % serial_id, chardev_info
            )
            if not hostfile:
                test.fail("Can't find the corresponding pty backend: %s" % chardev_info)
            fd_pty = os.open(hostfile[0], os.O_RDWR | os.O_NONBLOCK)
            os.close(fd_pty)
        elif backend == "file":
            filename = chardev_device.params["path"]
            with open(filename) as f:
                if "Linux" not in f.read():
                    test.fail("Guest boot fail with file backend.")
        elif backend == "null":
            session = vm.wait_for_login()
            session.cmd(create_delete_file)

        vm.verify_dmesg()
    vm.destroy()
