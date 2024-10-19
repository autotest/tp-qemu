import ctypes
import re

from virttest import error_context, qemu_qtree, utils_misc, utils_test

from provider import win_dev


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU windows guest vitio device irq check test

    1) Start guest with virtio device.
    2) Make sure driver verifier enabled in guest.
    3) Get irq info in guest and check the value of irq number.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_vectors_fqtree():
        """
        Get device vectors from qemu info qtree.
        """
        device_type = params["device_type"]
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(vm.monitor.info("qtree"))
        for node in qtree.get_nodes():
            if (
                isinstance(node, qemu_qtree.QtreeDev)
                and node.qtree["type"] == device_type
            ):
                vectors = node.qtree["vectors"].split()[0]
                return vectors

    def irq_check(session, device_name, devcon_folder, timeout):
        """
        Check virtio device's irq number, irq number should be greater than zero.

        :param session: use for sending cmd
        :param device_name: name of the specified device
        :param devcon_folder: Full path for devcon.exe
        :param timeout: Timeout in seconds.
        """
        hwids = win_dev.get_hwids(session, device_name, devcon_folder, timeout)
        if not hwids:
            test.error("Didn't find %s device info from guest" % device_name)
        if params.get("check_vectors", "no") == "yes":
            vectors = int(get_vectors_fqtree())
        for hwid in hwids:
            get_irq_cmd = params["get_irq_cmd"] % (devcon_folder, hwid)
            irq_list = re.findall(r":\s+(\d+)", session.cmd_output(get_irq_cmd), re.M)
            if not irq_list:
                test.error("device %s's irq checked fail" % device_name)
            irq_nums = len(irq_list)
            for irq_symbol in (ctypes.c_int32(int(irq)).value for irq in irq_list):
                if (irq_nums == 1 and irq_symbol < 0) or (
                    irq_nums > 1 and irq_symbol >= 0
                ):
                    test.fail("%s's irq is not correct." % device_name)
                elif irq_nums > 1 and (irq_nums != vectors):  # pylint: disable=E0606
                    test.fail("%s's irq nums not equal to vectors." % device_name)

    def set_msi_fguest(enable=True):
        """
        Disable or enable MSI from guest.
        """
        hwid = win_dev.get_hwids(session, device_name, devcon_folder, timeout)[0]
        session.cmd(params["msi_cmd"] % (hwid, 0 if enable else 1))

    driver = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver)
    device_name = params["device_name"]
    timeout = int(params.get("login_timeout", 360))
    restore_msi = False

    error_context.context("Boot guest with %s device" % driver, test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_verifier, timeout
    )
    if params.get("check_scsi_vectors", "no") == "yes":
        scsi_vectors = int(get_vectors_fqtree())
        scsi_queues = int(params["num_queues"])
        if scsi_vectors == scsi_queues + 3:
            test.log.info("Device vectors as expected")
            return
        else:
            test.fail(
                "Device vectors does not equal to num_queues+3.\n"
                "Device vectors as:%s\ndevice num_queues as:%s"
                % (scsi_vectors, scsi_queues)
            )

    error_context.context("Check %s's irq number" % device_name, test.log.info)
    devcon_folder = utils_misc.set_winutils_letter(session, params["devcon_folder"])
    if params.get("msi_cmd"):
        error_context.context("Set MSI in guest", test.log.info)
        set_msi_fguest(enable=True)
        session = vm.reboot(session=session)
        restore_msi = True
    irq_check(session, device_name, devcon_folder, timeout)

    if restore_msi:
        set_msi_fguest(enable=False)

    if session:
        session.close()
