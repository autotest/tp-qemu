import logging
from avocado.utils import process
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
            test.fail("Failed to get %s" % guest_info)
        return output.strip().splitlines()[-1]

    def compare_dev_tree(keyword, src):
        dst = get_info(session, keyword)
        if src != dst:
            test.fail("%s does not match to %s" % (src, dst))

    def check_nonexist_aliases(vm_session):
        """
        Check a nonexist device aliases.

        :param vm_session: session to checked vm.
        """

        status = vm_session.cmd_status(
            "test -f /proc/device-tree/aliases/cdrom")
        error_context.context(
            "Checking whether aliases file is indeed nonexisting", logging.info)
        if status == 0:
            test.fail("Nonexist cdrom aliases check failed.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 600))

    session = vm.wait_for_login(timeout=timeout)

    try:
        uuid = vm.get_uuid()
        compare_dev_tree("system-id", uuid)
        compare_dev_tree("vm,uuid", uuid)
        host_system_id = process.system_output(
            "echo `cat /proc/device-tree/system-id`", shell=True).strip().decode()
        compare_dev_tree("host-serial", host_system_id)
        compare_dev_tree("ibm,partition-name", params["main_vm"])

        check_nonexist_aliases(session)

    finally:
        session.close()
