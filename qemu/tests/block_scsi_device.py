import re

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test the scsi device inside guest.

    Scenario: from_delete_to_scan
        1. Boot guest with a scsi data disk.
        2. Delete the scsi data disk inside guest.
        3. Check the scsi data disk inside guest.
        4. Scan the scsi data disk inside guest.
        5. Check the scsi data disk inside guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def scan_scsi_device(scsi_addr):
        """Scan the scsi device."""
        error_context.context("Scan the scsi driver @%s." % scsi_addr, test.log.info)
        session.cmd(
            'echo "- - -" > /sys/class/scsi_host/host%s/scan' % scsi_addr.split(":")[0]
        )

    def delete_scsi_device(scsi_addr):
        """Delete the scsi drive."""
        error_context.context("Delete the scsi driver @%s." % scsi_addr, test.log.info)
        session.cmd("echo 1 > /sys/class/scsi_device/%s/device/delete" % scsi_addr)

    def get_scsi_addr_by_product(product_name):
        """Get the scsi address by virtio_scsi product option."""
        test.log.info("Get the scsi address by qemu product option.")
        addr_info = session.cmd("lsscsi | grep %s | awk '{print $1}'" % product_name)
        addr = re.search(r"((\d+\:){3}\d+)", addr_info).group(1)
        test.log.info("The scsi address of the product %s is %s.", product_name, addr)
        return addr

    def check_scsi_disk_by_address(scsi_addr):
        """Check whether the scsi disk is inside guest."""
        error_context.context(
            "Check whether the scsi disk(@%s) is inside guest." % scsi_addr,
            test.log.info,
        )
        scsi_info = session.cmd("lsscsi")
        test.log.info(scsi_info)
        return scsi_addr in scsi_info

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)

    product_name = params["product_name"]
    scsi_addr = get_scsi_addr_by_product(product_name)

    delete_scsi_device(scsi_addr)
    if check_scsi_disk_by_address(scsi_addr):
        test.fail(
            "The scsi disk(@%s) appears in guest "
            "after disable scsi drive." % scsi_addr
        )

    scan_scsi_device(scsi_addr)
    if not check_scsi_disk_by_address(scsi_addr):
        test.fail(
            "The scsi disk(@%s) does not appear in guest "
            "after enable scsi drive." % scsi_addr
        )
