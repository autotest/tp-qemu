"""
slof_user_interface.py include following case:
 1. Check the boot menu after press F12 button at the early stage of boot.
 2. SLOF user interface testing - boot.
 3. SLOF user interface testing - reset-all.
"""

import os
import re
import time

from virttest import env_process, error_context, utils_misc, utils_net

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify SLOF info by user interface.

    Step:
     Scenario 1:
      1.1 Boot a guest with at least two blocks, with "-boot menu=on",
          Press "F12" in the guest desktop at the early stage of booting
          process.
      1.2 Check the boot menu info whether are match with guest info.
      1.3 Select one of valid device to boot up the guest.
      1.4 Check whether errors in SLOF.
      1.5 Log in guest successfully.
      1.6 Ping external host ip successfully.

     Scenario 2:
      2.1. Boot the guest with spapr-vty and press 's' immediately when
           the guest boot up.
      2.2. Check the output of console, whether is stopped enter kernel.
      2.3. Type "boot" or "reset-all".
      2.4. Check guest whether boot up successfully.
      2.5. Log in guest successfully.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    STOP, F12 = range(2)
    enter_key = {STOP: "s", F12: "f12"}

    def _send_custom_key(keystr):
        """Send custom keyword to SLOF's user interface."""
        test.log.info('Sending "%s" to SLOF user interface.', keystr)
        for key in keystr:
            key = "minus" if key == "-" else key
            vm.send_key(key)
        vm.send_key("ret")

    def _send_key(key, custom=True, sleep=0.0):
        """Send keywords to SLOF's user interface."""
        obj_name = "select" if re.search(r"^\d+$", key) else key
        k_params = params.object_params(obj_name.replace("-", "_"))
        if custom:
            _send_custom_key(key)
        else:
            vm.send_key(key)
        time.sleep(sleep)
        content, _ = slof.get_boot_content(vm, 0, k_params["start"], k_params["end"])
        if content:
            test.log.info("Output of SLOF:\n%s", "".join(content))
            return "".join(content)
        return None

    def _check_menu_info(menu_info):
        """Check the menu info by each items."""
        bootable_num = ""
        for i in range(1, int(params["boot_dev_num"]) + 1):
            option = params["menu_option%d" % i]
            test.log.info(
                "Checking the device(%s) if is included in menu list.",
                "->".join(option.split()),
            )

            dev_type, hba_type, child_bus, addr = option.split()
            addr = re.sub(r"^0x0?", "", addr)
            pattern = re.compile(
                r"(\d+)\)\s+%s(\d+)?\s+:\s+/%s(\S+)?/%s@%s"
                % (dev_type, hba_type, child_bus, addr),
                re.M,
            )
            searched = pattern.search(menu_info)
            if not searched:
                test.fail(
                    "No such item(%s) in boot menu list." % "->".join(option.split())
                )
            if i == int(params["bootable_index"]):
                bootable_num = searched.group(1)
        return bootable_num

    def _enter_user_interface(mode):
        """Enter user interface."""
        o = utils_misc.wait_for(
            lambda: _send_key(enter_key[mode], False), ack_timeout, step=0.0
        )
        if not o:
            test.fail("Failed to enter user interface in %s sec." % ack_timeout)
        return o

    def _f12_user_interface_test():
        """Test f12 user interface."""
        menu_list = _enter_user_interface(F12)
        actual_num = len(re.findall(r"\d+\)", menu_list))
        dev_num = params["boot_dev_num"]
        if actual_num != int(dev_num):
            test.fail("The number of boot devices is not %s in menu list." % dev_num)
        if not utils_misc.wait_for(
            lambda: _send_key(_check_menu_info(menu_list), False), ack_timeout, step=0.0
        ):
            test.fail(
                "Failed to load after selecting boot device " "in %s sec." % ack_timeout
            )

    def _load_user_interface_test():
        """Test boot/reset-all user interface."""
        _enter_user_interface(STOP)
        if not utils_misc.wait_for(
            lambda: _send_key(keys, True, 3), ack_timeout, step=0.0
        ):
            test.fail("Failed to load after '%s' in %s sec." % (keys, ack_timeout))

    def _check_serial_log_status():
        """Check the status of serial log."""
        file_timeout = 30
        if not utils_misc.wait_for(
            lambda: os.path.isfile(vm.serial_console_log), file_timeout
        ):
            test.error("No found serial log during %s sec." % file_timeout)

    main_tests = {
        "f12": _f12_user_interface_test,
        "boot": _load_user_interface_test,
        "reset-all": _load_user_interface_test,
    }

    ack_timeout = params["ack_timeout"]
    keys = params["send_keys"]
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    _check_serial_log_status()
    main_tests[keys]()

    error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
    session = vm.wait_for_login(timeout=float(params["login_timeout"]))
    test.log.info("log into guest '%s' successfully.", vm.name)

    error_context.context("Try to ping external host.", test.log.info)
    extra_host_ip = utils_net.get_host_ip_address(params)
    session.cmd("ping %s -c 5" % extra_host_ip)
    test.log.info("Ping host(%s) successfully.", extra_host_ip)
    vm.destroy(gracefully=True)
