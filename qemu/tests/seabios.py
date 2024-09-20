import re

from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM Seabios test:
    1) Start guest with sga bios
    2) Check the sga bios messages(optional)
    3) Restart the vm, verify it's reset(optional)
    4) Display and check the boot menu order
    5) Start guest from the specified boot entry
    6) Log into the guest to verify it's up

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_output(session_obj):
        """
        Use the function to short the lines in the scripts
        """
        if params["enable_sga"] == "yes":
            output = session_obj.get_stripped_output()
        else:
            output = session_obj.get_output()
        return output

    def boot_menu():
        return re.search(boot_menu_hint, get_output(seabios_session))

    def boot_menu_check():
        return len(re.findall(boot_menu_hint, get_output(seabios_session))) > 1

    error_context.context("Start guest with sga bios", test.log.info)
    vm = env.get_vm(params["main_vm"])
    # Since the seabios is displayed in the beginning of guest boot,
    # booting guest here so that we can check all of sgabios/seabios
    # info, especially the correct time of sending boot menu key.
    vm.create()

    timeout = float(params.get("login_timeout", 240))
    boot_menu_key = params.get("boot_menu_key", "esc")
    restart_key = params.get("restart_key")
    boot_menu_hint = params.get("boot_menu_hint")
    boot_device = params.get("boot_device", "")
    sgabios_info = params.get("sgabios_info")

    seabios_session = vm.logsessions["seabios"]

    if sgabios_info:
        error_context.context("Display and check the SGABIOS info", test.log.info)

        def info_check():
            return re.search(sgabios_info, get_output(vm.serial_console))

        if not utils_misc.wait_for(info_check, timeout, 1):
            err_msg = "Cound not get sgabios message. The output"
            err_msg += " is %s" % get_output(vm.serial_console)
            test.fail(err_msg)

    if not (boot_menu_hint and utils_misc.wait_for(boot_menu, timeout, 1)):
        test.fail("Could not get boot menu message.")

    if restart_key:
        error_context.context("Restart vm and check it's ok", test.log.info)
        seabios_text = get_output(seabios_session)
        headline = seabios_text.split("\n")[0] + "\n"
        headline_count = seabios_text.count(headline)

        vm.send_key(restart_key)

        def reboot_check():
            return get_output(seabios_session).count(headline) > headline_count

        if not utils_misc.wait_for(reboot_check, timeout, 1):
            test.fail("Could not restart the vm")

        if not (boot_menu_hint and utils_misc.wait_for(boot_menu_check, timeout, 1)):
            test.fail("Could not get boot menu message after rebooting")

    # Send boot menu key in monitor.
    vm.send_key(boot_menu_key)

    error_context.context("Display and check the boot menu order", test.log.info)

    def get_list():
        return re.findall(r"^\d+\. (.*)\s", get_output(seabios_session), re.M)

    boot_list = utils_misc.wait_for(get_list, timeout, 1)

    if not boot_list:
        test.fail("Could not get boot entries list.")

    test.log.info("Got boot menu entries: '%s'", boot_list)
    for i, v in enumerate(boot_list, start=1):
        if re.search(boot_device, v, re.I):
            error_context.context("Start guest from boot entry '%s'" % v, test.log.info)
            vm.send_key(str(i))
            break
    else:
        test.fail("Could not get any boot entry match " "pattern '%s'" % boot_device)

    error_context.context("Log into the guest to verify it's up")
    session = vm.wait_for_login(timeout=timeout)
    session.close()
