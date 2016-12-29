import logging

from avocado.utils import process
from avocado.core import exceptions

from virttest import utils_misc
from virttest.qemu_devices import qcontainer
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    slof_device_tree test:
    steps:
    1. Boot up a guest.
    2. Check the guest device tree information
    3. Compare the value with expected result.
    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_info(vm_session, guest_info):
        """
        Check the corresponding information from vm.

        :param vm_session: session to checked vm.
        :return: corresponding prompt
        """
        (status, output) = vm_session.cmd_status_output(
            "echo `cat /proc/device-tree/%s`" % guest_info)
        if status != 0:
            raise exceptions.TestFail("Failed to get %s" % guest_info)
        return output.strip()

    def check_nonexist_aliases(vm_session, devices):
        """
        Check a nonexist device aliases.

        :param vm_session: session to checked vm.
        :return: corresponding prompt
        """

        status = vm_session.cmd_status(
            "test -f /proc/device-tree/aliases/cdrom")
        error_context.context(
            "Checking whether aliases file is indeed nonexisting", logging.info)
        if status == 0:
            raise exceptions.TestFail(
                "Nonexist cdrom aliases check failed.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 600))

    session = vm.wait_for_login(timeout=timeout)

    try:
        guest_system_id = get_info(session, "system-id")
        if guest_system_id != vm.get_uuid():
            raise exceptions.TestFail("Guest system id does not match to uuid")

        guest_uuid = get_info(session, "vm,uuid")
        if guest_uuid != vm.get_uuid():
            raise exceptions.TestFail(
                "Guest uuid does not match to expected id.")

        host_system_id = process.system_output(
            "echo `cat /proc/device-tree/system-id`", shell=True).strip()
        host_system_id_in_guest = get_info(session, "host-serial")
        if host_system_id != host_system_id_in_guest:
            raise exceptions.TestFail(
                "Host system id does not match to value in guest.")

        guest_partition_name = get_info(session, "ibm,partition-name")
        if guest_partition_name != params.get("main_vm"):
            raise exceptions.TestFail("Guest partition name is wrong.")

        qemu_binary = utils_misc.get_qemu_binary(params)
        devices = qcontainer.DevContainer(qemu_binary, vm, strict_mode="no")
        check_nonexist_aliases(session, devices)

    finally:
        session.close()
