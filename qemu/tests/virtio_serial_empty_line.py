from virttest import error_context
from virttest.utils_virtio_port import VirtioPortTest


def get_device_name_of_port(session, port_name):
    """
    Provide the device name of given port name, by checking its link
    e.g. for qemu cmd: -device virtserialport,id=idsjuuh7,name=vs1
        /dev/virtio-ports/vs1 -> /dev/vport0p1
        port name(vs1) -> device name(vport0p1)
    :param session: guest session
    :param port_name: the name of the port, defined in qemu cmd line
    :return: The device name of the port
    """
    virtio_port_dev_path = "/dev/virtio-ports/"
    port_path = "%s%s" % (virtio_port_dev_path, port_name)
    device_name = session.cmd_output_safe("readlink %s" % port_path)
    return device_name.strip("../\n")


def check_port_info(session, device_name, check_options):
    """
    Check the port info per given options
    :param session: guest session
    :param device_name: the device name of the port
    :param check_options: the options and values to be checked
    :return False if no such device in port info path; or dictionary
     including unmatched options: {option: [real_value, exp_value]}
    """
    port_info = get_port_info(session).get(device_name)
    if not port_info:
        return False
    unmatch_items = {}
    for option, exp_value in check_options.items():
        real_value = port_info.get(option)
        if exp_value != real_value:
            unmatch_items.update({option: [real_value, exp_value]})
    return unmatch_items


def get_port_info(session):
    """
    Get all the kernel debug info of virtio port
    :param session: guest session
    :return the dictionary of all port infos: {port_dev: {option: value}}
    """
    virtio_ports_debug_path = "/sys/kernel/debug/virtio-ports/"
    info_dict = {}
    port_devs = session.cmd_output_safe("ls %s" % virtio_ports_debug_path).split()
    for port_dev in port_devs:
        port_infos = session.cmd_output(
            "cat %s%s" % (virtio_ports_debug_path, port_dev)
        ).splitlines()
        port_dict = {}
        for line in port_infos:
            option, value = line.split(":")
            port_dict.update({option: value.strip()})
        info_dict.update({port_dev: port_dict})
    return info_dict


@error_context.context_aware
def run(test, params, env):
    """
    KVM virtio_console test

    1) Start guest with virtio-serial device
    2) Send empty line('\n') from host to guest or vice versa
    3) Check inside guest by "cat /sys/kernel/debug/virtio-ports/vport*p*"
       bytes_sent or bytes_received increased by 1

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    virtio_test = VirtioPortTest(test, env, params)

    (vm, guest_worker, port) = virtio_test.get_vm_with_single_port()
    session = vm.wait_for_login()

    device_name = get_device_name_of_port(session, port.name)
    try:
        if params["sender"] == "guest":
            # Send empty line('\n') from guest to host
            port.open()
            # 'echo' automatically adds '\n' in the end of each writing
            send_data_command = 'echo "" > /dev/%s' % device_name
            session.cmd(send_data_command, timeout=120)
            received_data = port.sock.recv(10)
            if received_data != b"\n":
                test.fail(
                    "Received data is not same as the data sent,"
                    " received %s, while expected '\n'" % received_data
                )
            check_option = {"bytes_sent": "1"}
        else:
            # Send empty line('\n') from host to guest
            port.open()
            port.sock.send(b"\n")
            guest_worker.cmd("virt.open('%s')" % port.name)
            guest_worker.cmd("virt.recv('%s', 0, mode=False)" % port.name)
            check_option = {"bytes_received": "1"}
        # Check options byte_sent or bytes_received
        check = check_port_info(session, device_name, check_option)
        if check is False:
            test.error("The debug info of %s is not found" % device_name)
        elif check:
            error_msg = ""
            for option, value in check.items():
                error_msg += "Option %s is %s," % (option, value[0])
                error_msg += " while expectation is: %s; " % value[1]
            test.fail("Check info mismatch: %s " % error_msg)
    finally:
        virtio_test.cleanup(vm, guest_worker)
        session.close()
