import re

from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    [seabios] Verify guest works well when using virtio-scsi with LUN not 0

    this case will:
    1) Boot guest with virtio-scsi disk and lun is not 0.
    2) Check boot menu list.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_output(session_obj):
        """
        Use the function to short the lines in the scripts
        """
        return session_obj.get_stripped_output()

    def boot_menu():
        return re.search(boot_menu_hint, get_output(seabios_session))

    def get_list():
        return re.findall(r"^\d+\. (.*)\s", get_output(seabios_session), re.M)

    timeout = float(params.get("boot_timeout", 60))
    boot_menu_key = params.get("boot_menu_key", "esc")
    boot_menu_hint = params.get("boot_menu_hint")
    check_pattern = params.get("check_pattern", "virtio-scsi Drive")
    img = params.objects("images")[0]
    lun = params["drive_port_%s" % img]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    seabios_session = vm.logsessions["seabios"]
    if not (boot_menu_hint and utils_misc.wait_for(boot_menu, timeout, 1)):
        test.fail("Could not get boot menu message.")

    error_context.context("Check boot menu list", test.log.info)
    vm.send_key(boot_menu_key)

    boot_list = utils_misc.wait_for(get_list, timeout, 1)
    if not boot_list:
        test.fail("Could not get boot entries list.")

    if check_pattern not in str(boot_list):
        test.fail("SCSI disk with lun %s cannot be found in boot menu" % lun)

    vm.destroy(gracefully=False)
