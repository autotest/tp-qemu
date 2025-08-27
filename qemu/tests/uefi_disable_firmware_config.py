import re

from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    A user is able to enter the firmware configuration app (not really just
    a boot menu) and do whatever they want, including changing boot order and
    devices. To avoid that, we can disable the configuration app by adding
    firmware config files using the qemu command line option -fw_cfg.
    If the config option is disabled, the corresponding boot device will not
    appear in BootManagerMenuApp.
    e.g. disable Firmware setup support, "EFI Firmware Setup" does not appear
    in BootManagerMenuApp and then user can not enter the firmware
    configuration app.

    In this case, the following config files will be covered.
    Check the boot device whether in BootManagerMenuApp when enabling/disabling
    the corresponding configuration.
    1. Firmware Config: opt/org.tianocore/FirmwareSetupSupport
       As the name suggests, this enables/disables Firmware setup support.
    2. Network: opt/org.tianocore/IPv4PXESupport
       As the name suggests, this enables/disables PXE network boot over IPv4.
    3. Network: opt/org.tianocore/IPv6PXESupport
       As the name suggests, this enables/disables PXE network boot over IPv6.
    4. Network: opt/org.tianocore/IPv4Support
       As the name suggests, this enables/disables HTTP network boot over IPv4.
    5. Network: opt/org.tianocore/IPv6Support
       As the name suggests, this enables/disables HTTP network boot over IPv6.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def boot_check(info):
        """
        boot info check
        """
        return re.search(info, vm.logsessions["seabios"].get_output(), re.S)

    boot_menu_key = params["boot_menu_key"]
    boot_menu_hint = params["boot_menu_hint"]
    boot_dev = params["boot_dev"]
    timeout = params.get_numeric("timeout", 30, float)
    firmware_config_enabled = params.get_boolean("firmware_config_enabled")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Navigate to Boot Manager Menu App", test.log.info)
    if not utils_misc.wait_for(lambda: boot_check(boot_menu_hint), timeout, 1):
        test.fail("Could not get boot manager menu message")
    vm.send_key(boot_menu_key)

    if firmware_config_enabled:
        error_context.context(
            f"Check boot device {boot_dev} in the Boot Manager Menu App", test.log.info
        )
        if not boot_check(boot_dev):
            test.fail(f"Could not get boot device {boot_dev} in Boot Manager Menu App")
    else:
        error_context.context(
            f"Check boot device {boot_dev} does not appear "
            "in the Boot Manager Menu App",
            test.log.info,
        )
        if boot_check(boot_dev):
            test.fail(f"Get unexpected boot device {boot_dev} in Boot Manager Menu App")
