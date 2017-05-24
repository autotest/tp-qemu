import logging

from qemu.tests import thin_provisioning

from avocado.core import exceptions

from autotest.client.shared import error
from autotest.client import os_dep

from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
      guest should always show unmap in /sys/bus target
      1)modeprobe scsi_debug
      2)using lsscsi to check that scsi_debug disk is fine
      3)check provisioning_mode of the disk in host
      4)boot up guest
      5)check provisioning_mode in guest
      :param test: QEMU test object
      :param params: Dictionary with the test parameters
      :param env: Dictionary with test environment.
      """

    # Destroy all vms to avoid emulated disk marked drity before start test
    for vm in env.get_all_vms():
        if vm:
            vm.destroy()
            env.unregister_vm(vm.name)

    os_dep.command("lsscsi")
    host_id, disk_name = thin_provisioning.get_scsi_disk(session=None)
    provisioning_mode = thin_provisioning.get_provisioning_mode(host_id, disk_name)
    error.context("The provisioning_mode is {:s}".format(provisioning_mode), logging.info)

    error.context("Boot guest with disk {:s}".format(disk_name), logging.info)
    vm_name = params["main_vm"]
    params["start_vm"] = "yes"
    params["image_name_image_other"] = disk_name
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    error.context("Get Guest pci num and disk name")
    guest_id, guest_disk_name = thin_provisioning.get_scsi_disk(session)

    guest_provisioning_mode = thin_provisioning.get_provisioning_mode(guest_id, guest_disk_name, session)
    if str(guest_provisioning_mode).strip() != "unmap":
        raise exceptions.TestFail(
            "The provisioning mode in guest is {:s}, it should be unmap".format(guest_provisioning_mode))
