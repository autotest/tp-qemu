import re
import logging
import time
from virttest import utils_misc
from virttest import env_process


def run(test, params, env):

    """
    KVM Seabios test:
    1) Check machine type and seabios bin file or 2) or 3).
    2) Start the guest with the empty file and check reboot time
    3) Start guest with sga bios
    4) Check the sga bios messages(optional)
    5) Restart the vm, verify it's reset(optional)
    6) Display and check the boot menu order
    7) Start guest from the specified boot entry
    8) Log into the guest to verify it's up

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

    def boot_menu_check():
        return (len(re.findall(boot_menu_hint,
                               get_output(seabios_session))) > 1)

    vm = env.get_vm(params["main_vm"])
    # Since the seabios is displayed in the beginning of guest boot,
    # booting guest here so that we can check all of sgabios/seabios
    # info, especially the correct time of sending boot menu key.
    vm.create()
    timeout = float(params.get("login_timeout", 240))
    boot_menu_key = params.get("boot_menu_key", 'f12')
    restart_key = params.get("restart_key")
    boot_menu_hint = params.get("boot_menu_hint")
    boot_device = params.get("boot_device", "")
    sgabios_info = params.get("sgabios_info")
    seabios_session = vm.logsessions['seabios']
    logging.info("Start guest with sga bios")

    def bois_bin_check():
        """
        1). Check machine type if match seabios bin file via monitor
        2). rhel6 machine type match bios.bin
        3). rhel7 machine type match bios-256k.bin
        """
        bios_bin_dic = {'rhel6': 'bios.bin', 'rhel7': 'bios-256k.bin'}
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        vm = env.get_vm(params["main_vm"])
        output = vm.monitor.info("roms")
        match_bin = re.search('bios.bin|bios-256k.bin', output)
        if match_bin:
            logging.info("Check seabios bin succeeded!")
        else:
            session = vm.wait_for_login(timeout=timeout)
            session.close()
            err_msg = "Check seabios bin failed"
            test.error(err_msg)
        vm.monitor.cmd("system_reset")

    def reboot_timeout_option():
        """
        1). Check boot option reboot-timeout
        2). guest will pause for reboot-timeout ms when boot failed, then reboot
        3). reboot-timeout default value is -1,guest will not reboot
        """
        if params["boot_reboot_timeout"]:
            rtime_cfg = int(params.get("boot_reboot_timeout"))
            rtime_sec = rtime_cfg/1000
            time.sleep(20)
            if rtime_sec < 60:
                time.sleep(60)
            else:
                time.sleep(rtime_sec)

            output = seabios_session.get_stripped_output()
            if 0 <= rtime_cfg <= 65535:
                pattern = "No bootable device.  Retrying in %s seconds" % rtime_sec
                match1 = re.search(pattern, output)
                if match1:
                    logging.info("Reboot timeout <65535 setting works!")
                else:
                    err_msg = "Reboot-timeout tests failed,para is %s" % rtime_sec
                    test.error(err_msg)
            elif rtime_cfg > 65535:
                pattern = "No bootable device.  Retrying in 65 seconds"
                match1 = re.search(pattern, output)
                if match1:
                    logging.info("Reboot timeout >65535 setting works!")
                else:
                    err_msg = "Reboot-timeout tests failed,para is %s" % rtime_sec
                    test.error(err_msg)
            elif rtime_cfg < 0:
                pattern1 = "No bootable device."
                pattern2 = " Retrying in"
                match1 = re.search(pattern1, output)
                match2 = re.search(pattern2, output)
                if match1 and not match2:
                    logging.info("Reboot timeout <0 setting works!")
                else:
                    err_msg = "Reboot-timeout tests failed,para is %s" % rtime_sec
                    test.error(err_msg)

    if sgabios_info:
        logging.info("Display and check the SGABIOS info")

        def info_check():
            return re.search(sgabios_info,
                             get_output(vm.serial_console))

        if not utils_misc.wait_for(info_check, timeout, 1):
            err_msg = "Cound not get sgabios message. The output"
            err_msg += " is %s" % get_output(vm.serial_console)
            test.error(err_msg)

    if restart_key:
        logging.info("Restart vm and check it's ok")

        if not (boot_menu_hint and utils_misc.wait_for(boot_menu, timeout, 1)):
            test.error("Could not get boot menu message.")

        seabios_text = get_output(seabios_session)
        headline = seabios_text.split("\n")[0] + "\n"
        headline_count = seabios_text.count(headline)

        vm.send_key(restart_key)

        def reboot_check():
            return get_output(seabios_session).count(headline) > headline_count

        if not utils_misc.wait_for(reboot_check, timeout, 1):
            test.error("Could not restart the vm")

        utils_misc.wait_for(boot_menu_check, timeout, 1)

    logging.info("Display and check the boot menu order")

    if not (boot_menu_hint and utils_misc.wait_for(boot_menu, timeout, 1)):
        test.error("Could not get boot menu message.")

    # Send boot menu key in monitor.
    vm.send_key(boot_menu_key)

    def get_list():
        return re.findall("^\d+\. (.*)\s", get_output(seabios_session), re.M)

    boot_list = utils_misc.wait_for(get_list, timeout, 1)

    if not boot_list:
        test.error("Could not get boot entries list.")

    logging.info("Got boot menu entries: '%s'", boot_list)
    for i, v in enumerate(boot_list, start=1):
        if re.search(boot_device, v, re.I):
            logging.info("Start guest from boot entry '%s'" % v)
            vm.send_key(str(i))
            break
    else:
        test.error("Could not get any boot entry match "
                   "pattern '%s'" % boot_device)

    logging.info("Log into the guest to verify it's up")
    #if not match_bin:
    #    session = vm.wait_for_login(timeout=timeout)
    #    session.close()
