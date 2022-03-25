from avocado.utils import process

from virttest import env_process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check the basic page size.
    Steps:
    1) Check system configuration basic page size on host.
    2) Boot a guest on the host.
    3) Check system configuration basic page size on guest.

    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """
    get_page_size = params.get('get_page_size')

    test.log.info("Check system configuration basic page size on host.")
    host_page_size = process.system_output(get_page_size).decode()
    if host_page_size != params.get("page_size_host"):
        test.fail("Host page size is %s not as expected." % host_page_size)

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    test.log.info("Check system configuration basic page size on guest.")
    guest_page_size = session.cmd(get_page_size).strip()
    if guest_page_size != params.get("page_size_guest"):
        test.fail("Guest page size is %s not as expected." % guest_page_size)
