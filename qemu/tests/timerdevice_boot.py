import logging
import re
import time

from autotest.client.shared import error
from autotest.client import utils

from virttest import data_dir
from virttest import storage
from virttest import utils_disk
from virttest import utils_test
from virttest import env_process
from virttest import funcatexit
from virttest import error_context


@error.context_aware
@error_context.context_aware
def run(test, params, env):
    """
    Timer device boot guest:

    1) Sync the host system time with ntp server
    2) Add some load on host (Optional)
    3) Boot the guest with specific clock source
    4) Check the clock source currently used on guest
    5) Do some file operation on guest (Optional)
    6) Check the system time on guest and host (Optional)
    7) Check the hardware time on guest and host (Optional)
    8) Sleep period of time before reboot (Optional)
    9) Reboot guest (Optional)
    10) Check the system time on guest and host (Optional)
    11) Check the hardware time on guest and host (Optional)

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def verify_guest_clock_source(session, expected):
        """
        Verify the clock source of the guest

        :param session: the guest session
        :param expected: the expected clock source
        """
        error.context("Check the current clocksource in guest", logging.info)
        cmd = "cat /sys/devices/system/clocksource/"
        cmd += "clocksource0/current_clocksource"
        if expected not in session.cmd(cmd):
            raise error.TestFail(
                "Guest didn't use '%s' clocksource" % expected)

    def verify_base_date_system_time():
        """
        When setting rtc_base to be a date,
        verify the guest system should be this date
        """
        time_command = params["time_command"]
        time_filter_re = params["time_filter_re"]
        time_format = params["time_format"]
        if params["os_type"] == "linux":
            time_command = "%s -u" % time_command
        (host_time, guest_time) = utils_test.get_time(session, time_command,
                                                      time_filter_re, time_format)
        guest_time = time.strftime('%Y-%m-%d %H', time.localtime(guest_time))
        logging.info("guest_time:%s", guest_time)
        if guest_time != '%s 00' % params["rtc_base"]:
            if session:
                session.close()
            test.fail("Guest time is %s and not from %s 00:00"
                      % (guest_time, params["rtc_base"]))

    def compare_time(host_time, guest_time, time_type):
        """
        Compare host time and system time, which difference should
        be less than the valued defined in cfg file

        :param host_time: the time of host
        :param guest_time: the time of guest
        :param time_type: the type of time. the value is "system" or "hardware"
        """
        drift = abs(float(host_time) - float(guest_time))
        if drift > timerdevice_drift_threshold:
            if session:
                session.close()
            test.fail("The guest's %s time is different with"
                      " host's. Host time: '%s', guest time:"
                      " '%s'" % (time_type, host_time, guest_time))

    def verify_guest_time():
        """
        Verify the difference of guest time and host time should
        be less than the value defined in the cfg file
        """
        error_context.context("Check the system time on guest and host",
                              logging.info)
        (host_sys_time, guest_sys_time) = utils_test.get_time(session,
                                                              time_command,
                                                              time_filter_re,
                                                              time_format)
        compare_time(host_sys_time, guest_sys_time, "system")
        error_context.context("Check the hardware time on guest and host",
                              logging.info)
        get_hw_time_cmd = params.get("get_hw_time_cmd")
        if get_hw_time_cmd:
            host_hw_time = utils.system_output(get_hw_time_cmd)
            guest_hw_time = session.cmd(get_hw_time_cmd)
            compare_time(host_hw_time, guest_hw_time, "hardware")

    error.context("Sync the host system time with ntp server", logging.info)
    utils.system("ntpdate clock.redhat.com")

    timerdevice_host_load_cmd = params.get("timerdevice_host_load_cmd")
    if timerdevice_host_load_cmd:
        error.context("Add some load on host", logging.info)
        utils.system(timerdevice_host_load_cmd)
        host_load_stop_cmd = params["timerdevice_host_load_stop_cmd"]
        funcatexit.register(env, params["type"], utils.system,
                            host_load_stop_cmd)

    error.context("Boot a guest with kvm-clock", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    timerdevice_clksource = params.get("timerdevice_clksource")
    if timerdevice_clksource:
        try:
            verify_guest_clock_source(session, timerdevice_clksource)
        except Exception:
            clksrc = timerdevice_clksource
            error.context("Shutdown guest")
            vm.destroy()
            env.unregister_vm(vm.name)
            error.context("Update guest kernel cli to '%s'" % clksrc,
                          logging.info)
            image_filename = storage.get_image_filename(params,
                                                        data_dir.get_data_dir())
            grub_file = params.get("grub_file", "/boot/grub2/grub.cfg")
            kernel_cfg_pattern = params.get("kernel_cfg_pos_reg",
                                            r".*vmlinuz-\d+.*")

            disk_obj = utils_disk.GuestFSModiDisk(image_filename)
            kernel_cfg_original = disk_obj.read_file(grub_file)
            try:
                logging.warn("Update the first kernel entry to"
                             " '%s' only" % clksrc)
                kernel_cfg = re.findall(kernel_cfg_pattern,
                                        kernel_cfg_original)[0]
            except IndexError, detail:
                raise error.TestError("Couldn't find the kernel config, regex"
                                      " pattern is '%s', detail: '%s'" %
                                      (kernel_cfg_pattern, detail))

            if "clocksource=" in kernel_cfg:
                kernel_cfg_new = re.sub("clocksource=.*?\s",
                                        "clocksource=%s" % clksrc, kernel_cfg)
            else:
                kernel_cfg_new = "%s %s" % (kernel_cfg,
                                            "clocksource=%s" % clksrc)

            disk_obj.replace_image_file_content(grub_file, kernel_cfg,
                                                kernel_cfg_new)

            error.context("Boot the guest", logging.info)
            vm_name = params["main_vm"]
            cpu_model_flags = params.get("cpu_model_flags")
            params["cpu_model_flags"] = cpu_model_flags + ",-kvmclock"
            env_process.preprocess_vm(test, params, env, vm_name)
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            session = vm.wait_for_login(timeout=timeout)

            error.context("Check the current clocksource in guest",
                          logging.info)
            verify_guest_clock_source(session, clksrc)

        error.context("Kill all ntp related processes")
        session.cmd("pkill ntp; true")

    if params.get("timerdevice_file_operation") == "yes":
        error.context("Do some file operation on guest", logging.info)
        session.cmd("dd if=/dev/zero of=/tmp/timer-test-file bs=1M count=100")
        return

    # Command to run to get the current time
    time_command = params["time_command"]
    # Filter which should match a string to be passed to time.strptime()
    time_filter_re = params["time_filter_re"]
    # Time format for time.strptime()
    time_format = params["time_format"]
    timerdevice_drift_threshold = params.get("timerdevice_drift_threshold", 3)

    if params["rtc_base"] in ("utc", "localtime"):
        verify_guest_time()
    else:
        if params["os_type"] == "linux":
            check_chronyd_active_cmd = params["check_chronyd_active_cmd"]
            chronyd_output = session.cmd_output_safe(check_chronyd_active_cmd)
            chronyd_active = re.search("active", chronyd_output)
            logging.info("chronyd_output:%s\n, chronyd_active:%s", chronyd_output, chronyd_active)
            # if chronyd service is enabled
            # Mask chronyd service, shutdown the guest
            # Boot guest again
            if chronyd_active:
                error_context.context("Mask chronyd service")
                mask_chronyd_cmd = params["mask_chronyd_cmd"]
                session.cmd_output_safe(mask_chronyd_cmd)
                error_context.context("Shoutdown the guest")
                vm.destroy()
                env.unregister_vm(vm.name)
                error_context.context("Boot the guest", logging.info)
                vm_name = params["main_vm"]
                env_process.preprocess_vm(test, params, env, vm_name)
                vm = env.get_vm(vm_name)
                vm.verify_alive()
                session = vm.wait_for_login(timeout=timeout)
        verify_base_date_system_time()

    if params.get("timerdevice_reboot_test") == "yes":
        sleep_time = params.get("timerdevice_sleep_time")
        if sleep_time:
            error.context("Sleep '%s' secs before reboot" % sleep_time,
                          logging.info)
            sleep_time = int(sleep_time)
            time.sleep(sleep_time)

        session = vm.reboot()

        if params["rtc_base"] in ("utc", "localtime"):
            verify_guest_time()
        else:
            verify_base_date_system_time()

    if params["os_type"] == "linux":
        # Unmask chronyd service
        if chronyd_active:
            error_context.context("Unmask chronyd service")
            unmask_chronyd_cmd = params["unmask_chronyd_cmd"]
            session.cmd_output_safe(unmask_chronyd_cmd)
    if session:
        session.close()
