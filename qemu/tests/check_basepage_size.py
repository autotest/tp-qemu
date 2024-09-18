import os

from avocado.utils import process
from virttest import env_process, error_context
from virttest.utils_numeric import normalize_data_size


@error_context.context_aware
def run(test, params, env):
    """
    Check the basic page size.
    Steps:
    1) Check system configuration basic page size on host.
    2) Check the basic page size mapping to the hugepage size on host.
    3) Boot a guest on the host.
    4) Check system configuration basic page size on guest.
    5) Check the basic page size mapping to the hugepage size on guest.

    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """
    get_basic_page = params.get("get_basic_page")
    local_pglist = params.get("local_pglist")
    basic_page_list = params.objects("basic_page_list")

    test.log.info("Check system configuration basic page size on host.")
    host_basic_page = process.system_output(get_basic_page).decode()
    if host_basic_page not in basic_page_list:
        test.fail("Host basic page size is %s not as expected." % host_basic_page)

    test.log.info("Check the basic page size mapping to the hugepage size on host.")
    host_basic_page = normalize_data_size("%sB" % host_basic_page, "K")
    hugepage_list = params.objects("mapping_pgsize_%sk" % host_basic_page)
    host_local_pglist = os.listdir(local_pglist)
    if sorted(host_local_pglist) != sorted(hugepage_list):
        test.fail("Host huge page size is %s not as expected." % host_local_pglist)

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    test.log.info("Check system configuration basic page size on guest.")
    guest_basic_page = session.cmd(get_basic_page).strip()
    if guest_basic_page not in basic_page_list:
        test.fail("Guest page size is %s not as expected." % guest_basic_page)

    test.log.info("Check the basic page size mapping to the hugepage size on guest.")
    guest_basic_page = normalize_data_size("%sB" % guest_basic_page, "K")
    hugepage_list = params.objects("mapping_pgsize_%sk" % guest_basic_page)
    guest_local_pglist = session.cmd("ls %s" % local_pglist).strip().split()
    if sorted(guest_local_pglist) != sorted(hugepage_list):
        test.fail("Guest huge page size is %s not as expected." % guest_local_pglist)
