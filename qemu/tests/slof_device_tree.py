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
        Get the corresponding information from vm.

        :param vm_session: session to checked vm.
        :return: if file does not exist return None, or not, return it's value
        """
        output = vm_session.cmd_output("echo `cat /proc/device-tree/%s`" % guest_info)
        if match_str in output:
            test.log.info(output)
            return None
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

        status = vm_session.cmd_status("test -f /proc/device-tree/aliases/cdrom")
        error_context.context(
            "Checking whether aliases file is indeed nonexisting", test.log.info
        )
        if status == 0:
            test.fail("Nonexist cdrom aliases check failed.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 600))

    session = vm.wait_for_login(timeout=timeout)
    match_str = params["match_str"]

    try:
        uuid = vm.get_uuid()
        compare_dev_tree("system-id", uuid)
        compare_dev_tree("vm,uuid", uuid)
        if get_info(session, "host-serial"):
            host_system_id = process.getoutput(
                "cat /proc/device-tree/system-id", verbose=True
            ).strip("\x00")
            compare_dev_tree("host-serial", host_system_id)
        compare_dev_tree("ibm,partition-name", params["main_vm"])

        check_nonexist_aliases(session)

    finally:
        session.close()
