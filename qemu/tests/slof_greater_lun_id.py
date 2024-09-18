"""
slof_greater_lun_id.py include following case:
 1.SLOF could support LUN ID greater than 255.
"""

from virttest import env_process, error_context, utils_net

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify SLOF info when LUN ID greater than 255.

    Step:
     1. Boot a guest with scsi system disk which lun=0
     2. Check no any errors from output of slof.
     3. Could login guest.
     4. Could ping external host ip.
     5. Shutdown guest.
     6. Change the lun id of scsi disk greater than 255(e.g 300).
     7. Boot this guest again.
     8. Repeat to do step 2 ~ 4.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    params["start_vm"] = "yes"
    start_pos = 0
    for params["drive_lun_image1"] in params["lun_ids"].split():
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
