import logging

from virttest import error_context
from virttest import utils_misc
from virttest import utils_test
from virttest.utils_test import BackgroundTest


@error_context.context_aware
def run(test, params, env):
    """
    Qemu hugepage memory stress test.
    Steps:
    1) System setup hugepages on host.
    2) Mount this hugepage to /mnt/kvm_hugepage.
    3) Run memory heavy stress inside guest.
    4) Check guest call trace in dmesg log.
    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """
    def heavyload_install():
        if session.cmd_status(test_installed_cmd) != 0:
            logging.warning("Could not find installed heavyload in guest, will"
                            " install it via winutils.iso ")
            winutil_drive = utils_misc.get_winutils_vol(session)
            if not winutil_drive:
                test.cancel("WIN_UTILS CDROM not found.")
            install_cmd = params["install_cmd"] % winutil_drive
            session.cmd(install_cmd)

    os_type = params["os_type"]
    verify_wait_timeout = params.get_numeric("verify_wait_timeout", 60)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    error_context.context("Run memory heavy stress in guest", logging.info)
    if os_type == "linux":
        stress_args = params["stress_custom_args"] % (
                params.get_numeric("mem") / 512)
        stress_test = utils_test.VMStress(vm, "stress",
                                          params, stress_args=stress_args)
        try:
            stress_test.load_stress_tool()
            utils_misc.wait_for(lambda: (stress_test.app_running is False), 30)
            stress_test.unload_stress()
            utils_misc.verify_dmesg(session=session)
        finally:
            stress_test.clean()
    else:
        install_path = params["install_path"]
        test_installed_cmd = 'dir "%s" | findstr /I heavyload' % install_path
        heavyload_install()
        error_context.context("Run heavyload inside guest.", logging.info)
        heavyload_bin = r'"%s\heavyload.exe" ' % install_path
        heavyload_options = ["/MEMORY %d" % (params.get_numeric("mem") / 512),
                             "/DURATION 30",
                             "/AUTOEXIT",
                             "/START"]
        start_cmd = heavyload_bin + " ".join(heavyload_options)
        stress_tool = BackgroundTest(session.cmd, (start_cmd, 30, 30))
        stress_tool.start()
        if not utils_misc.wait_for(stress_tool.is_alive, verify_wait_timeout):
            test.error("Failed to start heavyload process.")
        stress_tool.join(30)

    session.close()
