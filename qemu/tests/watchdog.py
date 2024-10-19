import os
import random
import re
import time

from aexpect.exceptions import ShellTimeoutError
from avocado.utils import process
from virttest import data_dir, env_process, error_context, utils_misc, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Configure watchdog, crash the guest and check if watchdog_action occurs.

    Test Step:
        1. see every function step
    Params:
        :param test: QEMU test object.
        :param params: Dictionary with test parameters.
        :param env: Dictionary with the test environment.
    """

    timeout = int(params.get("login_timeout", "360"))
    relogin_timeout = int(params.get("relogin_timeout", "240"))
    vm_arch_name = params["vm_arch_name"]

    watchdog_device_type = params.get("watchdog_device_type", "i6300esb")
    watchdog_action = params.get("watchdog_action", "reset")
    trigger_cmd = params.get("trigger_cmd", "echo c > /dev/watchdog")

    # internal function
    def _watchdog_device_check(test, session, watchdog_device):
        """
        Check the watchdog device have been found and init successfully. if not
        will raise error.
        """
        # when using ib700 or diag288 or itco, need modprobe it's driver manually.
        if watchdog_device == "ib700":
            session.cmd("modprobe ib700wdt")
        if watchdog_device == "diag288":
            session.cmd("modprobe diag288_wdt")
        if watchdog_device == "itco":
            session.cmd("modprobe iTCO_wdt")

        # when wDT is 6300esb need check pci info
        if watchdog_device == "i6300esb":
            error_context.context(
                "checking pci info to ensure have WDT" " device", test.log.info
            )
            session.cmd("echo 1 > /sys/bus/pci/rescan")
            o = session.cmd_output("lspci")
            if o:
                wdt_pci_info = re.findall(".*6300ESB Watchdog Timer", o)
                if not wdt_pci_info:
                    test.fail("Can not find watchdog pci")
            test.log.info("Found watchdog pci device : %s", wdt_pci_info)

        # checking watchdog init info using dmesg
        error_context.context("Checking watchdog load info", test.log.info)
        dmesg_info = params.get("dmesg_info", "(i6300ESB|ib700wdt).*init")
        module_check_cmd = params.get(
            "module_check_cmd", "dmesg | grep -i '%s' " % dmesg_info
        )
        (s, o) = session.cmd_status_output(module_check_cmd)
        if s != 0:
            error_msg = "Wactchdog device '%s' load/initialization failed "
            test.error(error_msg % watchdog_device)
        test.log.info("Watchdog device '%s' add and init successfully", watchdog_device)
        test.log.debug("Init info : '%s'", o)

    def _trigger_watchdog(session, trigger_cmd=None):
        """
        Trigger watchdog action
        Params:
            @session: guest connect session.
            @trigger_cmd: cmd trigger the watchdog
        """
        if trigger_cmd is not None:
            error_context.context(
                ("Trigger Watchdog action using:'%s'." % trigger_cmd), test.log.info
            )
            session.sendline(trigger_cmd)

    def _action_check(test, session, watchdog_action):
        """
        Check whether or not the watchdog action occurred. if the action was
        not occurred will raise error.
        """
        # when watchdog action is pause, shutdown, reset, poweroff
        # the vm session will lost responsive

        def check_guest_reboot(pattern):
            start_time = time.time()
            while (time.time() - start_time) < vm.REBOOT_TIMEOUT:
                if pattern in vm.serial_console.get_output().strip():
                    return True
            return False

        response_timeout = int(params.get("response_timeout", "240"))
        error_context.context(
            "Check whether or not watchdog action '%s' took"
            " effect" % watchdog_action,
            test.log.info,
        )
        if watchdog_action == "inject-nmi":
            if vm_arch_name in ("x86_64", "i686"):
                if not utils_misc.wait_for(
                    lambda: "NMI received" in session.cmd_output("dmesg"),
                    response_timeout,
                    0,
                    1,
                ):
                    test.fail(
                        "Guest didn't receive dmesg with 'NMI received',"
                        "after action '%s'." % watchdog_action
                    )
                msg = session.cmd_output("dmesg").splitlines()[-8:]
                test.log.info("Guest received dmesg info: %s", msg)
            elif vm_arch_name in ("ppc64", "ppc64le"):
                rebooted = check_guest_reboot(params["guest_reboot_pattern"])
                if not rebooted:
                    test.fail(
                        "Guest isn't rebooted after watchdog action '%s'"
                        % watchdog_action
                    )
                test.log.info("Try to login the guest after reboot")
                session = vm.wait_for_login(timeout=timeout)
        if not utils_misc.wait_for(
            lambda: not session.is_responsive(), response_timeout, 0, 1
        ):
            if watchdog_action in ("none", "debug", "inject-nmi"):
                test.log.info("OK, the guest session is responsive still")
            else:
                txt = "It seems action '%s' took no" % watchdog_action
                txt += " effect, guest is still responsive."
                test.fail(txt)

        # when action is poweroff or shutdown(without no-shutdown option),
        # the vm will dead, and qemu exit.
        # The others the vm monitor still responsive, can report the vm status.
        if watchdog_action == "poweroff" or (
            watchdog_action == "shutdown" and params.get("disable_shutdown") != "yes"
        ):
            if not utils_misc.wait_for(lambda: vm.is_dead(), response_timeout, 0, 1):
                txt = "It seems '%s' action took no effect, " % watchdog_action
                txt += "guest is still alive!"
                test.fail(txt)
        else:
            if watchdog_action == "pause":
                f_param = "paused"
            elif watchdog_action == "shutdown":
                f_param = "shutdown"
            else:
                f_param = "running"

            if not utils_misc.wait_for(
                lambda: vm.monitor.verify_status(f_param), response_timeout, 5, 1
            ):
                test.log.debug("Monitor status is:%s", vm.monitor.get_status())
                txt = "It seems action '%s' took no effect" % watchdog_action
                txt += " , Wrong monitor status!"
                test.fail(txt)

        # when the action is reset, need can relogin the guest.
        if watchdog_action == "reset":
            test.log.info("Try to login the guest after reboot")
            vm.wait_for_login(timeout=relogin_timeout)
        test.log.info("Watchdog action '%s' come into effect.", watchdog_action)

    def check_watchdog_support():
        """
        check the host qemu-kvm support watchdog device
        Test Step:
        1. Send qemu command 'qemu -watchdog ?'
        2. Check the watchdog type that the host support.
        """
        qemu_binary = utils_misc.get_qemu_binary(params)

        watchdog_type_check = params.get("watchdog_type_check", " -device '?'")
        qemu_cmd = qemu_binary + watchdog_type_check

        # check the host support watchdog types.
        error_context.context(
            "Checking whether or not the host support"
            " WDT '%s'" % watchdog_device_type,
            test.log.info,
        )
        watchdog_device = process.system_output(
            "%s 2>&1" % qemu_cmd, shell=True
        ).decode()
        if watchdog_device:
            if re.findall(watchdog_device_type, watchdog_device, re.I):
                test.log.info(
                    "The host support '%s' type watchdog device", watchdog_device_type
                )
            else:
                test.log.info(
                    "The host support watchdog device type is: '%s'", watchdog_device
                )
                test.cancel("watdog %s isn't supported" % watchdog_device_type)
        else:
            test.cancel("No watchdog device supported by the host!")

    def guest_boot_with_watchdog():
        """
        check the guest can boot with watchdog device
        Test Step:
        1. Boot guest with watchdog device
        2. Check watchdog device have been initialized successfully in guest
        """
        _watchdog_device_check(test, session, watchdog_device_type)

    def watchdog_action_test():
        """
        Watchdog action test
        Test Step:
        1. Boot guest with watchdog device
        2. Check watchdog device have been initialized successfully in guest
        3.Trigger wathchdog action through open /dev/watchdog
        4.Ensure watchdog_action take effect.
        """

        _watchdog_device_check(test, session, watchdog_device_type)
        _trigger_watchdog(session, trigger_cmd)
        _action_check(test, session, watchdog_action)

    def magic_close_support():
        """
        Magic close the watchdog action.
        Test Step:
        1. Boot guest with watchdog device
        2. Check watchdog device have been initialized successfully in guest
        3. Inside guest, trigger watchdog action"
        4. Inside guest, before heartbeat expires, close this action"
        5. Wait heartbeat timeout check the watchdog action deactive.
        """

        response_timeout = int(params.get("response_timeout", "240"))
        magic_cmd = params.get("magic_close_cmd", "echo V > /dev/watchdog")

        _watchdog_device_check(test, session, watchdog_device_type)
        _trigger_watchdog(session, trigger_cmd)

        # magic close
        error_context.context("Magic close is start", test.log.info)
        _trigger_watchdog(session, magic_cmd)

        if utils_misc.wait_for(
            lambda: not session.is_responsive(), response_timeout, 0, 1
        ):
            error_msg = "Watchdog action took effect, magic close FAILED"
            test.fail(error_msg)
        test.log.info("Magic close took effect.")

    def migration_when_wdt_timeout():
        """
        Migration when WDT timeout
        Test Step:
        1. Boot guest with watchdog device
        2. Check watchdog device have been initialized successfully in guest
        3. Start VM with watchdog device, action reset|pause
        4. Inside RHEL guest, trigger watchdog
        5. Before WDT timeout, do vm migration
        6. After migration, check the watchdog action take effect
        """

        mig_timeout = float(params.get("mig_timeout", "3600"))
        mig_protocol = params.get("migration_protocol", "tcp")
        mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2

        _watchdog_device_check(test, session, watchdog_device_type)
        _trigger_watchdog(session, trigger_cmd)

        error_context.context(
            "Do migration(protocol:%s),Watchdog have" " been triggered." % mig_protocol,
            test.log.info,
        )
        args = (mig_timeout, mig_protocol, mig_cancel_delay)
        migrate_thread = utils_misc.InterruptedThread(vm.migrate, args)
        migrate_thread.start()
        _action_check(test, session, watchdog_action)
        migrate_thread.join(timeout=mig_timeout)

    def hotplug_unplug_watchdog_device():
        """
        Hotplug/unplug watchdog device
        Test Step:
        1. Start VM with "-watchdog-action pause" CLI option
        2. Add WDT via monitor
        3. Trigger watchdog action in guest
        4. Remove WDT device through monitor cmd "device_del"
        5. Resume and relogin the guest, check the device have been removed.
        """

        session = vm.wait_for_login(timeout=timeout)
        o = session.cmd_output("lspci")
        if o:
            wdt_pci_info = re.findall(".*6300ESB Watchdog Timer", o)
            if wdt_pci_info:
                test.fail("Can find watchdog pci")

        plug_watchdog_device = params.get("plug_watchdog_device", "i6300esb")
        machine_type = params.get("machine_type")
        watchdog_device_add = "device_add driver=%s, id=%s" % (
            plug_watchdog_device,
            "watchdog",
        )
        if machine_type == "q35":
            watchdog_device_add += ",bus=pcie-pci-bridge-0,addr=0x1f"
        watchdog_device_del = "device_del id=%s" % "watchdog"

        error_context.context(
            ("Hotplug watchdog device '%s'" % plug_watchdog_device), test.log.info
        )
        vm.monitor.send_args_cmd(watchdog_device_add)

        # wait watchdog device init
        time.sleep(5)
        _watchdog_device_check(test, session, plug_watchdog_device)
        _trigger_watchdog(session, trigger_cmd)
        _action_check(test, session, watchdog_action)

        error_context.context("Hot unplug watchdog device", test.log.info)
        vm.monitor.send_args_cmd(watchdog_device_del)

        error_context.context(
            "Resume the guest, check the WDT have" " been removed", test.log.info
        )
        vm.resume()
        session = vm.wait_for_login(timeout=timeout)
        o = session.cmd_output("lspci")
        if o:
            wdt_pci_info = re.findall(".*6300ESB Watchdog Timer", o)
            if wdt_pci_info:
                test.fail("Oops, find watchdog pci, unplug failed")
            test.log.info("The WDT remove successfully")

    def stop_cont_test():
        """
        Check if the emulated watchdog devices work properly with the stop/
        continue operation
        """

        response_timeout = int(params.get("response_timeout", "240"))
        _watchdog_device_check(test, session, watchdog_device_type)
        vm.monitor.clear_event("WATCHDOG")
        _trigger_watchdog(session, trigger_cmd)
        vm.pause()
        if utils_misc.wait_for(
            lambda: vm.monitor.get_event("WATCHDOG"), timeout=response_timeout
        ):
            test.fail(
                "Watchdog action '%s' still took effect after pausing "
                "VM." % watchdog_action
            )
        test.log.info(
            "Watchdog action '%s' didn't take effect after pausing "
            "VM, it is expected.",
            watchdog_action,
        )
        vm.resume()
        if not utils_misc.wait_for(
            lambda: vm.monitor.get_event("WATCHDOG"), timeout=response_timeout
        ):
            test.fail(
                "Watchodg action '%s' didn't take effect after resuming "
                "VM." % watchdog_action
            )
        _action_check(test, session, watchdog_action)

    def watchdog_test_suit():
        """
        Run watchdog-test-framework to verify the function of emulated watchdog
        devices.
        Test steps of the framework are as follows:
        1) Set up the watchdog with a 30 second timeout.
        2) Ping the watchdog for 60 seconds.  During this time the guest should
        run normally.
        3) Stop pinging the watchdog and just count up.  If the virtual watchdog
        device is set correctly, then the watchdog action (eg. pause) should
        happen around the 30 second mark.
        """

        _watchdog_device_check(test, session, watchdog_device_type)
        watchdog_test_lib = params["watchdog_test_lib"]
        src_path = os.path.join(data_dir.get_deps_dir(), watchdog_test_lib)
        test_dir = os.path.basename(watchdog_test_lib)
        session.cmd_output("rm -rf /home/%s" % test_dir)
        vm.copy_files_to(src_path, "/home")
        session.cmd_output("cd /home/%s && make" % test_dir)
        try:
            session.cmd_output("./watchdog-test --yes &", timeout=130)
        except ShellTimeoutError:
            # To judge if watchdog action happens after 30s
            o = session.get_output().splitlines()[-1]
            if 27 <= int(o.rstrip("...")) <= 32:
                _action_check(test, session, watchdog_action)
            else:
                test.fail("Watchdog action doesn't happen after 30s.")
        else:
            test.fail("Watchdog test suit doesn't run successfully.")
        finally:
            vm.resume()
            session.cmd_output("pkill watchdog-test")
            session.cmd_output("rm -rf /home/%s" % test_dir)

    def heartbeat_test():
        """
        Heartbeat test for i6300esb
        Test steps:
        1.Start VM with "-watchdog-action pause" CLI option
        2.Set heartbeat value and reload the i6300esb module
        3.Trigger wathchdog action through open /dev/watchdog
        4.Ensure watchdog_action takes effect after $heartbeat.
        """
        del_module_cmd = params["del_module_cmd"]
        reload_module_cmd = params["reload_module_cmd"]
        _watchdog_device_check(test, session, watchdog_device_type)
        error_context.context(
            "set heartbeat value and reload the i6300esb " "module", test.log.info
        )
        session.cmd(del_module_cmd)
        heartbeat = params["heartbeat"]
        if heartbeat == "random_value":
            heartbeat = random.randint(1, 20)
        else:
            heartbeat = eval(heartbeat)
        dmesg_cmd = params["dmesg_cmd"]
        session.cmd(dmesg_cmd)
        session.cmd_output(reload_module_cmd % heartbeat)
        if heartbeat < -2147483648 or heartbeat > 2147483647:
            o = session.cmd_output("dmesg | grep -i 'i6300esb.*invalid'")
            if o:
                test.log.info(
                    "Heartbeat value %s is out of range, it is " "expected.", heartbeat
                )
            else:
                test.fail("No invalid heartbeat info in dmesg.")
        elif -2147483648 <= heartbeat < 1 or 2046 < heartbeat <= 2147483647:
            o = session.cmd_output("dmesg | grep -i 'heartbeat=30'")
            if not o:
                test.fail(
                    "Heartbeat value isn't default 30 sec in dmesg, it " "should be."
                )
            heartbeat = 30
        elif 1 <= heartbeat <= 2046:
            o = session.cmd_output("dmesg | grep -i 'heartbeat=%s'" % heartbeat)
            if not o:
                test.fail("Heartbeat value isn't %s sec in dmesg" % heartbeat)
        if heartbeat <= 2147483647 and heartbeat > -2147483648:
            _watchdog_device_check(test, session, watchdog_device_type)
            _trigger_watchdog(session, trigger_cmd)
            error_context.context(
                "Watchdog will fire after %s s" % heartbeat, test.log.info
            )
            start_time = time.time()
            end_time = start_time + float(heartbeat) + 2
            while not vm.monitor.verify_status("paused"):
                if time.time() > end_time:
                    test.fail(
                        "Monitor status is:%s, watchdog action '%s' didn't take"
                        "effect" % (vm.monitor.get_status(), watchdog_action)
                    )
                time.sleep(1)
            guest_pause_time = time.time() - start_time
            if abs(guest_pause_time - float(heartbeat)) <= 2:
                test.log.info(
                    "Watchdog action '%s' took effect after '%s's.",
                    watchdog_action,
                    guest_pause_time,
                )
            else:
                test.fail(
                    "Watchdog action '%s' took effect after '%s's, it is earlier"
                    " than expected." % (watchdog_action, guest_pause_time)
                )

    # main procedure
    test_type = params.get("test_type")
    watchdog_device_type = params.get("watchdog_device_type")
    if watchdog_device_type == "itco":
        pass
    else:
        check_watchdog_support()

    error_context.context("'%s' test starting ... " % test_type, test.log.info)
    error_context.context(
        "Boot VM with WDT(Device:'%s', Action:'%s'),"
        " and try to login" % (watchdog_device_type, watchdog_action),
        test.log.info,
    )
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)

    if params.get("setup_runlevel") == "yes":
        error_context.context("Setup the runlevel for guest", test.log.info)
        utils_test.qemu.setup_runlevel(params, session)

    if test_type in locals():
        test_running = locals()[test_type]
        try:
            test_running()
        finally:
            vm.destroy()
    else:
        test.error("Oops test %s doesn't exist, have a check please." % test_type)
