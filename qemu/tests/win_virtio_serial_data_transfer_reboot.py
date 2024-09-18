import os

from avocado.utils import process
from virttest import data_dir, error_context, qemu_virtio_port, utils_misc


# This decorator makes the test function aware of context strings
@error_context.context_aware
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

    def receive_data(test, session, serial_receive_cmd, data_file):
        output = session.cmd_output(serial_receive_cmd, timeout=30)
        with open(data_file, "r") as data_file:
            ori_data = data_file.read()
        if ori_data.strip() != output.strip():
            err = "Data lost during transfer. Origin data is:\n%s" % ori_data
            err += "Guest receive data:\n%s" % output
            test.fail(err)

    def transfer_data(test, session, receive_cmd, send_cmd, data_file, n_time):
        txt = "Transfer data betwwen guest and host for %s times" % n_time
        error_context.context(txt, test.log.info)
        for num in range(n_time):
            test.log.info("Data transfer repeat %s/%s.", num + 1, n_time)
            try:
                args = (test, session, receive_cmd, data_file)
                guest_receive = utils_misc.InterruptedThread(receive_data, args)
                guest_receive.daemon = True
                guest_receive.start()
                process.system(send_cmd, timeout=30, shell=True)
            finally:
                if guest_receive:
                    guest_receive.join(10)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    check_cmd = params.get("check_vioser_status_cmd", "verifier /querysettings")
    output = session.cmd(check_cmd, timeout=360)
    error_context.context(
        "Make sure vioser.sys verifier enabled in guest.", test.log.info
    )
    if "vioser.sys" not in output:
        verify_cmd = params.get(
            "vioser_verify_cmd", "verifier.exe /standard /driver vioser.sys"
        )
        session.cmd(verify_cmd, timeout=360, ok_status=[0, 2])
        session = vm.reboot(session=session, timeout=timeout)
        output = session.cmd(check_cmd, timeout=360)
        if "vioser.sys" not in output:
            test.error("Fail to veirfy vioser.sys driver.")
    guest_scripts = params["guest_scripts"]
    guest_path = params.get("guest_script_folder", "C:\\")
    error_context.context("Copy test scripts to guest.", test.log.info)
    for script in guest_scripts.split(";"):
        link = os.path.join(data_dir.get_deps_dir("win_serial"), script)
        vm.copy_files_to(link, guest_path, timeout=60)
    port_name = vm.virtio_ports[0].qemu_id
    host_file = get_virtio_port_host_file(vm, port_name)
    data_file = params["data_file"]
    data_file = os.path.join(data_dir.get_deps_dir("win_serial"), data_file)
    send_script = params.get("host_send_script", "serial-host-send.py")
    send_script = os.path.join(data_dir.get_deps_dir("win_serial"), send_script)
    serial_send_cmd = "`command -v python python3 | head -1` %s %s %s" % (
        send_script,
        host_file,
        data_file,
    )
    receive_script = params.get(
        "guest_receive_script", "VirtIoChannel_guest_recieve.py"
    )
    receive_script = "%s%s" % (guest_path, receive_script)
    serial_receive_cmd = "python %s %s " % (receive_script, port_name)
    n_time = int(params.get("repeat_times", 20))

    transfer_data(test, session, serial_receive_cmd, serial_send_cmd, data_file, n_time)
    error_context.context("Reboot guest.", test.log.info)
    session = vm.reboot(session=session, timeout=timeout)
    transfer_data(test, session, serial_receive_cmd, serial_send_cmd, data_file, n_time)
    error_context.context("Reboot guest by system_reset qmp command.", test.log.info)
    session = vm.reboot(session=session, method="system_reset", timeout=timeout)
    if session:
        session.close()
