import re

from virttest import error_context, qemu_qtree, utils_misc, utils_test

from provider import win_dev


@error_context.context_aware
def run(test, params, env):
    """
    virtio mode compatibility test:
    1) Boot guest with related virtio devices with modern/transitional/legacy mode;
    2) Verify virtio mode from qtree;
    3) Verify virtio mode from guest;

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def verify_virtio_mode_qtree():
        """
        Verify that virtio mode setting in qtree are correct.
        """
        device_type = params["device_type"]
        qtree = qemu_qtree.QtreeContainer()
        try:
            qtree.parse_info_qtree(vm.monitor.info("qtree"))
        except AttributeError:
            test.cancel("Monitor deson't supoort qtree, skip this test")
        disable_modern = None
        disable_legacy = None
        for node in qtree.get_nodes():
            if (
                isinstance(node, qemu_qtree.QtreeDev)
                and node.qtree["type"] == device_type
            ):
                disable_modern = node.qtree["disable-modern"]
                disable_legacy = node.qtree["disable-legacy"].strip('"')
        if (
            disable_modern != params["virtio_dev_disable_modern"]
            or disable_legacy != params["virtio_dev_disable_legacy"]
        ):
            test.fail(
                "virtio mode in qtree is not correct, details are %s %s"
                % (disable_modern, disable_legacy)
            )

    def verify_virtio_mode_guest_win(session, virtio_mode):
        """
        Verify virtio mode in windows guests. If device is in modern mode,
        device id should be larger than 1040. Else device memory range need
        to checked futher.

        :param session: shell Object
        :param virtio_mode: VirtIO mode for the device
        """
        device_name = params["device_name"]
        driver_name = params["driver_name"]
        driver_verifier = params.get("driver_verifier", driver_name)
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_verifier
        )
        devcon_folder = utils_misc.set_winutils_letter(session, params["devcon_folder"])

        hwid = win_dev.get_hwids(session, device_name, devcon_folder)[0]
        device_id = int(hwid[17:21])

        if device_id > 1040:
            guest_mode = "modern"
        else:
            guest_mode = win_memory_range(session, devcon_folder, hwid, virtio_mode)

        if virtio_mode != guest_mode:
            test.fail("virtio mode in guest is not correct!")

    def win_memory_range(session, devcon_folder, hwid, virtio_mode):
        """
        Check devices' memory range in windows guests. Memory range should be
        larger than 0xFFF in transitional mode, no more than 0xFFF in legacy mode.

        :param session: shell Object
        :param devcon_folder: devcon.exe folder path
        :param hwid: hardware id of a specific device
        :param virtio_mode: VirtIO mode for the device
        """
        mem_check_cmd = '%sdevcon.exe resources @"%s" | find "MEM"' % (
            devcon_folder,
            hwid,
        )
        status, output = session.cmd_status_output(mem_check_cmd)
        guest_mode = "legacy"
        if status == 0:
            for out in output.split("\n")[0:-2]:
                out = re.split(r":+", out)[1].split("-")
                if int(out[1], 16) - int(out[0], 16) - int("0xFFF", 16):
                    guest_mode = "transitional"
        return guest_mode

    def verify_virtio_mode_guest_linux(session):
        """
        Verify virtio mode in linux guests. The specific bit should be 1 when
        in modern and transitional mode.

        :param session: shell Object
        """
        pci_info = session.cmd_output("lspci -n")
        pci_id_pattern = params["pci_id_pattern"]
        pci_n = re.findall(pci_id_pattern, pci_info)[0]
        if not pci_n:
            test.error("Can't get the pci id for device")

        cmd = "grep . /sys/bus/pci/devices/0000:%s/virtio*/features" % pci_n
        virtio_bit = int(session.cmd_output(cmd)[32])
        if virtio_bit != (virtio_mode != "legacy"):
            test.fail("Fail as the virtio bit is not correct")

    def verify_virtio_mode_guest(session, virtio_mode):
        """
        Verify virtio mode in guests.

        :param session: shell Object
        :param virtio_mode: VirtIO mode for the device
        """
        os_type = params["os_type"]
        if os_type == "windows":
            verify_virtio_mode_guest_win(session, virtio_mode)
        else:
            verify_virtio_mode_guest_linux(session)

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    virtio_mode = params["virtio_mode"]

    error_context.context("Verify virtio mode in qtree", test.log.info)
    verify_virtio_mode_qtree()

    error_context.context("Verify virtio mode in guest", test.log.info)
    verify_virtio_mode_guest(session, virtio_mode)
