"""
slof_boot.py include following case:
 1. Boot guest from virtio HDD and check guest can be boot successfully.
 2. Boot guest from virtio HDD with dataplane and check guest can be boot
    successfully.
 3. Boot guest from virtio scsi HDD and check guest can be boot
    successfully.
 4. Boot guest from virtio scsi HDD with dataplane and check guest can be
    boot successfully.
 5. Boot guest from spapr-vscsi HDD and check guest can be boot
    successfully.
 6. SLOF can boot from virtio-scsi disk behind pci-bridge.
 7. SLOF can boot from virtio-blk-pci disk behind pci-bridge.
 8. Test supported block size of boot disk for virtio-blk-pci.
 9. Test supported block size of boot disk for virtio-scsi.
"""

import re

from avocado.utils import process
from virttest import error_context, utils_net

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify SLOF info by booting guest with different devices and options.

    Step:
     1. Boot a guest with different storage devices and others options.
        Including storage devices:
         a. virtio-blk
         b. virtio-blk with dataplane
         c. virtio-scsi
         d. vritio-scsi with dataplane
         e. spapr-vscsi
         g. virtio-scsi disk behind pci-bridge
         h. virtio-blk-pci disk behind pci-bridge
         i. virtio-blk with block size
         j. virtio-scsi with block size
     2. Check if any error info in output of SLOF during booting.
     3. Check if booted from specified storage device successfully by
        reading "Trying to load:  from: /xxx/xxx/xxx ..." from output of
        SLOF.
     4. Check if login guest successfully.
     5. Guest could ping external host ip.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _get_pci_bridge_addr(id):
        dev_info_list = re.findall(r"\s+-device pci-bridge,\S+\s+", vm.qemu_command)
        for dev_info in dev_info_list:
            if ("id=" + id) in dev_info:
                return re.search(r"(addr)=(\w+)", dev_info).group(2)

    def _verify_boot_status(boot_dev, content):
        dev_params = params.object_params(boot_dev)
        child_addr = dev_params.get("child_addr")
        sub_child_addr = dev_params.get("sub_child_addr", None)
        parent_bus = dev_params.get("parent_bus")
        child_bus = dev_params.get("child_bus")
        if child_bus == "pci-bridge":
            pci_bus_id = params.get("pci_bus_image1", None)
            child_addr = _get_pci_bridge_addr(pci_bus_id)
        if sub_child_addr:
            fail_info = "Failed to boot from %s device (%s@%s)." % (
                boot_dev,
                child_addr,
                sub_child_addr,
            )
            ret_info = "Booted from %s device (%s@%s) successfully." % (
                boot_dev,
                child_addr,
                sub_child_addr,
            )
        else:
            fail_info = "Failed to boot from %s device(@%s)." % (boot_dev, child_addr)
            ret_info = "Booted from %s device(@%s) successfully." % (
                boot_dev,
                child_addr,
            )
        if not slof.verify_boot_device(
            content, parent_bus, child_bus, child_addr, sub_child_addr
        ):
            test.fail(fail_info)
        test.log.info(ret_info)

    o = process.getoutput(params.get("check_slof_version")).strip()
    test.log.info("Check the version of SLOF: '%s'", o)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    content, _ = slof.wait_for_loaded(vm, test)

    error_context.context("Check the output of SLOF.", test.log.info)
    slof.check_error(test, content)

    _verify_boot_status(params["boot_dev_type"], content)

    error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    test.log.info("log into guest '%s' successfully.", vm.name)

    error_context.context("Try to ping external host.", test.log.info)
    extra_host_ip = utils_net.get_host_ip_address(params)
    s, o = session.cmd_status_output("ping %s -c 5" % extra_host_ip)
    test.log.debug(o)
    if s:
        test.fail("Failed to ping external host.")
    test.log.info("Ping host(%s) successfully.", extra_host_ip)

    session.close()
    vm.destroy(gracefully=True)
