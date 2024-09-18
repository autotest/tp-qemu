from aexpect import ShellTimeoutError
from virttest import error_context, utils_misc, utils_net, utils_test
from virttest.utils_windows import virtio_win


@error_context.context_aware
def run(test, params, env):
    """
    Bind netkvm protocol to netkvm adapter, and enabled manually without VF

    1) Boot a windows guest
    2) Enable driver verifier
    3) Install VIOPROT protocol
    4) Bind netkvm protocol to netkvm adapter
    5) Ping out

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    # workaround for driver has no signature
    def send_key(vm, key):
        # Send key to guest
        for i in key:
            vm.send_key(i)

    timeout = params.get_numeric("timeout", 360)
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)
    error_context.context(
        "Check if the driver is installed and " "verified", test.log.info
    )
    driver_verifier = params["driver_verifier"]
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_verifier, timeout
    )
    error_context.context("Install VIOPROT protocol", test.log.info)
    media_type = params["virtio_win_media_type"]
    try:
        get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
        get_product_dirname = getattr(virtio_win, "product_dirname_%s" % media_type)
        get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
    except AttributeError:
        test.error("Not supported virtio win media type '%s'", media_type)
    viowin_ltr = get_drive_letter(session)
    if not viowin_ltr:
        test.error("Could not find virtio-win drive in guest")
    guest_name = get_product_dirname(session)
    if not guest_name:
        test.error("Could not get product dirname of the vm")
    guest_arch = get_arch_dirname(session)
    if not guest_arch:
        test.error("Could not get architecture dirname of the vm")

    inf_middle_path = (
        "{name}\\{arch}" if media_type == "iso" else "{arch}\\{name}"
    ).format(name=guest_name, arch=guest_arch)
    inf_find_cmd = 'dir /b /s %s\\vioprot.inf | findstr "\\%s\\\\"'
    inf_find_cmd %= (viowin_ltr, inf_middle_path)
    inf_path = session.cmd(inf_find_cmd, timeout=timeout).strip()

    test.log.info("Will install inf file found at '%s'", inf_path)
    install_cmd = params["install_cmd"] % inf_path

    # workaround for driver has no signature
    key_to_install_driver = params.get("key_to_install_driver").split(";")
    try:
        session.cmd_status_output(install_cmd, timeout=30)
    except ShellTimeoutError:
        send_key(vm, key_to_install_driver)
    if utils_misc.wait_for(
        lambda: params["check_info"]
        in session.cmd_output(params["check_installation_cmd"]),
        30,
        15,
        5,
    ):
        test.log.info("inf file installation successfully")
    else:
        test.error("inf file installation failed")

    error_context.context("Bind netkvm protocol to netkvm adapter")
    nic_mac = vm.get_mac_address(0)
    connection_id = utils_net.get_windows_nic_attribute(
        session, "macaddress", nic_mac, "netconnectionid", timeout=timeout
    )
    bind_cmd = params["bind_cmd"] % connection_id
    status, output = session.cmd_status_output(bind_cmd, timeout=timeout)
    if status:
        test.error("Bind netkvm protocol failed, output=%s" % output)

    error_context.context("Ping out from guest", test.log.info)
    host_ip = utils_net.get_host_ip_address(params)
    status, output = utils_net.ping(host_ip, count=10, timeout=60, session=session)
    if status:
        test.fail("Ping %s failed, output=%s" % (host_ip, output))
