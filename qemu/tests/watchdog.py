import re
import time
import logging

from avocado.utils import process
from virttest import error_context
from virttest import utils_misc
from virttest import env_process
from virttest import utils_test


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

    timeout = int(params.get("login_timeout", '360'))
    relogin_timeout = int(params.get("relogin_timeout", '240'))

    watchdog_device_type = params.get("watchdog_device_type", "i6300esb")
    watchdog_action = params.get("watchdog_action", "reset")
    trigger_cmd = params.get("trigger_cmd", "echo c > /dev/watchdog")

    # internal function
    def _watchdog_device_check(test, session, watchdog_device):
        """
        Check the watchdog device have been found and init successfully. if not
        will raise error.
        """
        # when using ib700 or diag288, need modprobe it's driver manually.
        if watchdog_device == "ib700":
            session.cmd("modprobe ib700wdt")
        if watchdog_device == "diag288":
            session.cmd("modprobe diag288_wdt")

        # when wDT is 6300esb need check pci info
        if watchdog_device == "i6300esb":
            error_context.context("checking pci info to ensure have WDT"
                                  " device", logging.info)
            o = session.cmd_output("lspci")
            if o:
                wdt_pci_info = re.findall(".*6300ESB Watchdog Timer", o)
                if not wdt_pci_info:
                    test.fail("Can not find watchdog pci")
            logging.info("Found watchdog pci device : %s" % wdt_pci_info)

        # checking watchdog init info using dmesg
        error_context.context("Checking watchdog load info", logging.info)
        dmesg_info = params.get("dmesg_info", "(i6300ESB|ib700wdt).*init")
        module_check_cmd = params.get("module_check_cmd",
                                      "dmesg | grep -i '%s' " % dmesg_info)
        (s, o) = session.cmd_status_output(module_check_cmd)
        if s != 0:
            error_msg = "Wactchdog device '%s' load/initialization failed "
            test.error(error_msg % watchdog_device)
        logging.info("Watchdog device '%s' add and init successfully"
                     % watchdog_device)
        logging.debug("Init info : '%s'" % o)

    def _trigger_watchdog(session, trigger_cmd=None):
        """
        Trigger watchdog action
        Params:
            @session: guest connect session.
            @trigger_cmd: cmd trigger the watchdog
        """
        if trigger_cmd is not None:
            error_context.context(("Trigger Watchdog action using:'%s'." %
                                   trigger_cmd), logging.info)
            session.sendline(trigger_cmd)

    def _action_check(test, session, watchdog_action):
        """
        Check whether or not the watchdog action occurred. if the action was
        not occurred will raise error.
        """
        # when watchdog action is pause, shutdown, reset, poweroff
        # the vm session will lost responsive
        response_timeout = int(params.get("response_timeout", '240'))
        error_context.context("Check whether or not watchdog action '%s' took"
                              " effect" % watchdog_action, logging.info)
        if not utils_misc.wait_for(lambda: not session.is_responsive(),
                                   response_timeout, 0, 1):
            if watchdog_action == "none" or watchdog_action == "debug":
                logging.info("OK, the guest session is responsive still")
            else:
                txt = "It seems action '%s' took no" % watchdog_action
                txt += " effect, guest is still responsive."
                test.fail(txt)

        # when action is poweroff or shutdown(without no-shutdown option),
        # the vm will dead, and qemu exit.
        # The others the vm monitor still responsive, can report the vm status.
        if (watchdog_action == "poweroff" or (watchdog_action == "shutdown" and
                                              params.get("disable_shutdown") != "yes")):
            if not utils_misc.wait_for(lambda: vm.is_dead(),
                                       response_timeout, 0, 1):
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
                lambda: vm.monitor.verify_status(f_param),
                    response_timeout, 0, 1):
                logging.debug("Monitor status is:%s" % vm.monitor.get_status())
                txt = "It seems action '%s' took no effect" % watchdog_action
                txt += " , Wrong monitor status!"
                test.fail(txt)

        # when the action is reset, need can relogin the guest.
        if watchdog_action == "reset":
            logging.info("Try to login the guest after reboot")
            vm.wait_for_login(timeout=relogin_timeout)
        logging.info("Watchdog action '%s' come into effect." %
                     watchdog_action)

    def check_watchdog_support():
        """
        check the host qemu-kvm support watchdog device
        Test Step:
        1. Send qemu command 'qemu -watchdog ?'
        2. Check the watchdog type that the host support.
        """
        qemu_binary = utils_misc.get_qemu_binary(params)

        watchdog_type_check = params.get(
            "watchdog_type_check", " -watchdog '?'")
        qemu_cmd = qemu_binary + watchdog_type_check

        # check the host support watchdog types.
        error_context.context("Checking whether or not the host support"
                              " WDT '%s'" % watchdog_device_type, logging.info)
        watchdog_device = process.system_output("%s 2>&1" % qemu_cmd,
                                                shell=True)
        if watchdog_device:
            if re.findall(watchdog_device_type, watchdog_device, re.I):
                logging.info("The host support '%s' type watchdog device" %
                             watchdog_device_type)
            else:
                logging.info("The host support watchdog device type is: '%s'"
                             % watchdog_device)
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

        response_timeout = int(params.get("response_timeout", '240'))
        magic_cmd = params.get("magic_close_cmd", "echo V > /dev/watchdog")

        _watchdog_device_check(test, session, watchdog_device_type)
        _trigger_watchdog(session, trigger_cmd)

        # magic close
        error_context.context("Magic close is start", logging.info)
        _trigger_watchdog(session, magic_cmd)

        if utils_misc.wait_for(lambda: not session.is_responsive(),
                               response_timeout, 0, 1):
            error_msg = "Watchdog action took effect, magic close FAILED"
            test.fail(error_msg)
        logging.info("Magic close took effect.")

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

        error_context.context("Do migration(protocol:%s),Watchdog have"
                              " been triggered." % mig_protocol, logging.info)
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
        watchdog_device_add = ("device_add driver=%s, id=%s"
                               % (plug_watchdog_device, "watchdog"))
        watchdog_device_del = ("device_del id=%s" % "watchdog")

        error_context.context(("Hotplug watchdog device '%s'" %
                               plug_watchdog_device), logging.info)
        vm.monitor.send_args_cmd(watchdog_device_add)

        # wait watchdog device init
        time.sleep(5)
        _watchdog_device_check(test, session, plug_watchdog_device)
        _trigger_watchdog(session, trigger_cmd)
        _action_check(test, session, watchdog_action)

        error_context.context("Hot unplug watchdog device", logging.info)
        vm.monitor.send_args_cmd(watchdog_device_del)

        error_context.context("Resume the guest, check the WDT have"
                              " been removed", logging.info)
        vm.resume()
        session = vm.wait_for_login(timeout=timeout)
        o = session.cmd_output("lspci")
        if o:
            wdt_pci_info = re.findall(".*6300ESB Watchdog Timer", o)
            if wdt_pci_info:
                test.fail("Oops, find watchdog pci, unplug failed")
            logging.info("The WDT remove successfully")

    # main procedure
    test_type = params.get("test_type")
    check_watchdog_support()

    error_context.context("'%s' test starting ... " % test_type, logging.info)
    error_context.context("Boot VM with WDT(Device:'%s', Action:'%s'),"
                          " and try to login" %
                          (watchdog_device_type, watchdog_action),
                          logging.info)
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)

    if params.get("setup_runlevel") == "yes":
        error_context.context("Setup the runlevel for guest", logging.info)
        utils_test.qemu.setup_runlevel(params, session)

    if (test_type in locals()):
        test_running = locals()[test_type]
        test_running()
    else:
        test.error("Oops test %s doesn't exist, have a check please."
                   % test_type)
