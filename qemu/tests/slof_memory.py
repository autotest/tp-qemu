"""
slof_memory.py include following case:
 1. CAS(client-architecture-support) response with large maxmem.
"""

from virttest import env_process, error_context, utils_net

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify SLOF info with maxmem options.

    Step:
     1. Boot a guest with "maxmem=512G".
      a. Check no errors from output of SLOF.
      b. Log in guest successfully.
      c. Ping external host ip successfully.
     2. Shutdown the guest then boot it again with "maxmem=1024G".
      a. Check no errors from output of SLOF.
      b. Log in guest successfully.
      c. Ping external host ip successfully.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    start_pos = 0
    for mem in params["maxmem_mem_list"].split():
        params["maxmem_mem"] = mem

        env_process.preprocess_vm(test, params, env, params["main_vm"])
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        content, next_pos = slof.wait_for_loaded(vm, test, start_pos)

        error_context.context("Check the output of SLOF.", test.log.info)
        slof.check_error(test, content)

        error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
        timeout = float(params.get("login_timeout", 240))
        session = vm.wait_for_login(timeout=timeout)
        test.log.info("log into guest '%s' successfully.", vm.name)

        error_context.context("Try to ping external host.", test.log.info)
        extra_host_ip = utils_net.get_host_ip_address(params)
        session.cmd("ping %s -c 5" % extra_host_ip)
        test.log.info("Ping host(%s) successfully.", extra_host_ip)

        session.close()
        vm.destroy(gracefully=True)
        start_pos = next_pos
