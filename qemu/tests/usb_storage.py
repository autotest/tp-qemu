import re
import uuid

import aexpect
from virttest import error_context, utils_misc, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Test usb storage devices in the guest.

    1) Create a image file by qemu-img
    2) Boot up a guest
    3) Hotplug a usb storage (optional)
    4) Check usb storage information via monitor
    5) Check usb information by executing guest command
    6) Check usb serial option (optional)
    7) Check usb removable option (optional)
    8) Check usb min_io_size/opt_io_size option (optional)
    9) Hotunplug the usb storage (optional)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    @error_context.context_aware
    def _verify_string(regex_str, string, expect_result, search_opt=0):
        """
        Verify USB storage device in monitor

        :param regex_str: Regex for checking command output
        :param string: The string which will be checked
        :param expect_result: The expected string
        :param search_opt: Search option for re module.
        """

        def _compare_str(act, exp, ignore_case):
            def str_func_1(x):
                return x

            def str_func_2(x):
                return x.lower()

            str_func = str_func_1
            if ignore_case:
                str_func = str_func_2

            if str_func(act) != str_func(exp):
                return "Expected: '%s', Actual: '%s'" % (str_func(exp), str_func(act))
            return ""

        ignore_case = False
        if search_opt & re.I == re.I:
            ignore_case = True

        error_context.context(
            "Finding matched sub-string with regex" " pattern '%s'" % regex_str,
            test.log.info,
        )
        m = re.findall(regex_str, string, search_opt)
        if not m:
            test.log.debug(string)
            test.error("Could not find matched sub-string")

        error_context.context(
            "Verify matched string is same as expected", test.log.info
        )
        actual_result = m[0]
        if "removable" in regex_str:
            if actual_result in ["on", "yes", "true"]:
                actual_result = "on"
            if actual_result in ["off", "no", "false"]:
                actual_result = "off"

        fail_log = []
        if isinstance(actual_result, tuple):
            for i, v in enumerate(expect_result):
                ret = _compare_str(actual_result[i], v, ignore_case)
                if ret:
                    fail_log.append(ret)
        else:
            ret = _compare_str(actual_result, expect_result[0], ignore_case)
            if ret:
                fail_log.append(ret)

        if fail_log:
            test.log.debug(string)
            test.fail("Could not find expected string:\n %s" % ("\n".join(fail_log)))

    def _do_io_test_guest():
        utils_test.run_virt_sub_test(test, params, env, "format_disk")

    @error_context.context_aware
    def _restart_vm(options):
        if vm.is_alive():
            vm.destroy()

        for option, value in options.items():
            params[option] = value
        error_context.context("Restarting VM")
        vm.create(params=params)
        vm.verify_alive()

    def _login():
        return vm.wait_for_login(timeout=login_timeout)

    def _get_usb_disk_name_in_guest(session):
        def _get_output():
            cmd = "ls -l /dev/disk/by-path/* | grep usb"
            try:
                return session.cmd(cmd).strip()
            except aexpect.ShellCmdError:
                return ""

        output = utils_misc.wait_for(
            _get_output, login_timeout, step=5, text="Wait for getting USB disk name"
        )
        devname = re.findall(r"sd\w", output)
        if devname:
            return devname[0]
        return "sda"

    @error_context.context_aware
    def _check_serial_option(serial, regex_str, expect_str):
        error_context.context("Set serial option to '%s'" % serial, test.log.info)
        _restart_vm({"blk_extra_params_stg": "serial=" + serial})

        error_context.context("Check serial option in monitor", test.log.info)
        output = str(vm.monitor.info("qtree"))
        _verify_string(regex_str, output, [expect_str], re.S)

        error_context.context("Check serial option in guest", test.log.info)
        session = _login()
        output = session.cmd("lsusb -v")
        if serial not in ["EMPTY_STRING", "NO_EQUAL_STRING"]:
            # Verify in guest when serial is set to empty/null is meaningless.
            _verify_string(serial, output, [serial])
        session.close()

    @error_context.context_aware
    def _check_removable_option(removable, expect_str):
        error_context.context("Set removable option to '%s'" % removable, test.log.info)
        _restart_vm({"removable_stg": removable})

        error_context.context("Check removable option in monitor", test.log.info)
        output = str(vm.monitor.info("qtree"))
        regex_str = r"usb-storage.*?removable = (.*?)\s"
        _verify_string(regex_str, output, [removable], re.S)

        error_context.context("Check removable option in guest", test.log.info)
        session = _login()
        cmd = "dmesg | grep %s" % _get_usb_disk_name_in_guest(session)
        output = session.cmd(cmd)
        _verify_string(expect_str, output, [expect_str], re.I)
        session.close()

    @error_context.context_aware
    def _check_io_size_option(min_io_size="512", opt_io_size="0"):
        error_context.context(
            "Set min_io_size to %s, opt_io_size to %s" % (min_io_size, opt_io_size),
            test.log.info,
        )
        opt = {}
        opt["min_io_size_stg"] = min_io_size
        opt["opt_io_size_stg"] = opt_io_size

        _restart_vm(opt)

        error_context.context("Check min/opt io_size option in monitor", test.log.info)
        output = str(vm.monitor.info("qtree"))
        regex_str = r"usb-storage.*?min_io_size = (\d+).*?opt_io_size = (\d+)"
        _verify_string(regex_str, output, [min_io_size, opt_io_size], re.S)

        error_context.context("Check min/opt io_size option in guest", test.log.info)
        session = _login()
        d = _get_usb_disk_name_in_guest(session)
        cmd = "cat /sys/block/%s/queue/{minimum,optimal}_io_size" % d

        output = session.cmd(cmd)
        # Note: If set min_io_size = 0, guest min_io_size would be set to
        # 512 by default.
        if min_io_size != "0":
            expected_min_size = min_io_size
        else:
            expected_min_size = "512"
        _verify_string(r"(\d+)\n(\d+)", output, [expected_min_size, opt_io_size])
        session.close()

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    login_timeout = int(params.get("login_timeout", 360))
    hotplug_unplug = params["with_hotplug_unplug"] == "yes"
    repeat_times = int(params.get("usb_repeat_times", "1"))
    for rt in range(1, repeat_times + 1):
        disk_hotplugged = []
        if hotplug_unplug:
            error_context.context("Hotplug the %s times." % rt, test.log.info)
            image_name = params.objects("images")[-1]
            image_params = params.object_params(image_name)
            devices = vm.devices.images_define_by_params(
                image_name, image_params, "disk", None, False, None
            )
            for dev in devices:
                ret = vm.devices.simple_hotplug(dev, vm.monitor)
                if ret[1] is False:
                    test.fail(
                        "Failed to hotplug device '%s'. Output:\n%s" % (dev, ret[0])
                    )
            disk_hotplugged.append(devices[-1])

        error_context.context("Check usb device information in monitor", test.log.info)
        output = str(vm.monitor.info("usb"))
        if "Product QEMU USB MSD" not in output:
            test.log.debug(output)
            test.fail("Could not find mass storage device")

        error_context.context("Check usb device information in guest", test.log.info)
        session = _login()
        output = session.cmd(params["chk_usb_info_cmd"])
        # No bus specified, default using "usb.0" for "usb-storage"
        for i in params["chk_usb_info_keyword"].split(","):
            _verify_string(i, output, [i])
        session.close()
        _do_io_test_guest()

        # this part is linux only
        if params.get("check_serial_option") == "yes":
            error_context.context("Check usb serial option", test.log.info)
            serial = uuid.uuid4().hex[:20]
            regex_str = r'usb-storage.*?serial = "(.*?)"\s'
            _check_serial_option(serial, regex_str, serial)

            test.log.info("Check this option with some illegal string")
            test.log.info("Set usb serial to a empty string")
            # An empty string, ""
            serial = "EMPTY_STRING"
            regex_str = r"usb-storage.*?serial = (.*?)\s"
            _check_serial_option(serial, regex_str, '""')

            test.log.info("Leave usb serial option blank")
            serial = "NO_EQUAL_STRING"
            _check_serial_option(serial, regex_str, '"on"')

        if params.get("check_removable_option") == "yes":
            error_context.context("Check usb removable option", test.log.info)
            removable = "on"
            expect_str = "Attached SCSI removable disk"
            _check_removable_option(removable, expect_str)

            removable = "off"
            expect_str = "Attached SCSI disk"
            _check_removable_option(removable, expect_str)

        if params.get("check_io_size_option") == "yes":
            error_context.context("Check usb min/opt io_size option", test.log.info)
            _check_io_size_option("0", "0")
            # NOTE: Guest can't recognize correct value which we set now,
            # So comment these test temporary.
            # _check_io_size_option("1024", "1024")
            # _check_io_size_option("4096", "4096")

        if hotplug_unplug:
            error_context.context("Hotunplug the %s times." % rt, test.log.info)
            for dev in disk_hotplugged:
                ret = vm.devices.simple_unplug(dev, vm.monitor)
                if ret[1] is False:
                    test.fail(
                        "Failed to unplug device '%s'. Output:\n%s" % (dev, ret[0])
                    )
