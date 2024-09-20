import re
import time

from avocado.utils import process
from virttest import arch, env_process, error_context

from qemu.tests.qemu_guest_agent import QemuGuestAgentTest


@error_context.context_aware
def run(test, params, env):
    """
    Clock check after savevm/loadvm

    1. Load kvm module with "kvmclock_periodic_sync=N"
    2. Stop chronyd service and sync time with ntp server on host
    3. Boot vm and check current clocksource in vm
    4. Stop chronyd service and sync time with ntp server on vm
    5. Run samevm and loadvm with qmp monitor
    6. Run 'guest-set-time' with qemu-guest-agent
    7. Run 'rtc-reset-reinjection' with qmp monitor
    8. Query time offset with ntp server on vm,
       it should be less than 3 seconds

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _load_kvm_module_with_kvmclock_periodic_sync(module_param):
        """
         Load kvm module with kvmclock_periodic_sync=N/Y

        :params module_param: the value of kvmclock_periodic_sync
        """
        error_context.context(
            "Load kvm module with kvmclock_periodic_sync=%s" % module_param,
            test.log.info,
        )
        check_modules = arch.get_kvm_module_list()
        error_context.context("check_module: '%s'" % check_modules, test.log.info)
        check_modules.reverse()
        for module in check_modules:
            rm_mod_cmd = "modprobe -r %s" % module
            process.system(rm_mod_cmd, shell=True)
        check_modules.reverse()
        for module in check_modules:
            load_mod_cmd = "modprobe %s" % module
            if module == "kvm":
                load_mod_cmd = "%s kvmclock_periodic_sync=%s" % (
                    load_mod_cmd,
                    module_param,
                )
            process.system(load_mod_cmd, shell=True)
        check_mod_cmd = params["check_mod_cmd"]
        if process.system_output(check_mod_cmd).decode() != module_param:
            test.error(
                "Cannot load kvm module with kvmclock_periodic_sync=%s" % module_param
            )

    def setup():
        """
        On host, load kvm module with "kvmclock_periodic_sync=N"
        sync time with ntp server and boot the guest
        """
        if arch.ARCH not in ("ppc64", "ppc64le"):
            _load_kvm_module_with_kvmclock_periodic_sync("N")
        error_context.context("Sync host time with ntp server", test.log.info)
        ntp_cmd = params.get("ntp_cmd")
        status = process.system(ntp_cmd, shell=True)
        if status != 0:
            test.cancel("Fail to sync host time with ntp server.")

        error_context.context("Boot the guest", test.log.info)
        params["start_vm"] = "yes"
        vm = env.get_vm(params["main_vm"])
        env_process.preprocess_vm(test, params, env, vm.name)
        vm.verify_alive()
        return vm

    def cleanup():
        """
        Close session and load kvm module with "kvmclock_periodic_sync=Y"
        """
        if session:
            session.close()
        env.unregister_vm(vm.name)
        vm.destroy(gracefully=False, free_mac_addresses=True)
        if arch.ARCH not in ("ppc64", "ppc64le"):
            _load_kvm_module_with_kvmclock_periodic_sync("Y")

    def setup_gagent():
        """
        Execute guest agent command 'guest-set-time' in host side.
        """
        gagent_test = QemuGuestAgentTest(test, params, env)
        gagent_test.initialize(test, params, env)
        gagent_test.setup(test, params, env)
        return gagent_test

    def run_qmp_cmd(qmp_port, qmp_cmd):
        """
        Run a qmp command

        :params qmp_port: the guest qmp port to send qmp command
        :params qmp_cmd: qmp command
        """
        output = qmp_port.send_args_cmd(qmp_cmd)
        test.log.info("QMP command: '%s' \n Output: '%s'", qmp_cmd, output)

    def query_ntp_time():
        """
        On guest, query clock offset
        """
        ntp_query_cmd = params["ntp_query_cmd"]
        output = session.cmd_output_safe(ntp_query_cmd)
        error_context.context("Verify guest time offset", test.log.info)
        offset = float(re.findall(r"[+|-]*\s*(\d+\.\d+)\s*sec", output)[-1])
        error_context.context("offset: '%.2f'" % offset, test.log.info)
        exptected_time_drift = params.get("expected_time_drift", 3)
        if offset > float(exptected_time_drift):
            test.fail("After loadvm, the time drift of guest is too large.")

    vm = setup()
    session = vm.wait_for_login()
    try:
        error_context.context("Check the clocksource currently in use", test.log.info)
        clocksource = params.get("clocksource", "kvm-clock")
        clocksource_cmd = "cat /sys/devices/system/clocksource/clocksource0"
        clocksource_cmd += "/current_clocksource"
        currentsource = session.cmd_output_safe(clocksource_cmd)
        if clocksource not in currentsource:
            test.cancel("Mismatch clocksource, current clocksource: %s", currentsource)
        error_context.context(
            "Stop chronyd and sync guest time with ntp server", test.log.info
        )
        ntp_cmd = params.get("ntp_cmd")
        status, output = session.cmd_status_output(ntp_cmd)
        if status != 0:
            test.error("Failed to sync guest time with ntp server.")
        error_context.context("Setup qemu-guest-agent in guest", test.log.info)
        gagent = setup_gagent()

        qmp_ports = vm.get_monitors_by_type("qmp")
        qmp_port = None
        if qmp_ports:
            qmp_port = qmp_ports[0]
        else:
            test.cancel("Incorrect configuration, no QMP monitor found.")
        error_context.context("Save/load VM", test.log.info)
        qmp_savevm_cmd = params["qmp_savevm_cmd"]
        run_qmp_cmd(qmp_port, qmp_savevm_cmd)
        qmp_loadvm_cmd = params["qmp_loadvm_cmd"]
        run_qmp_cmd(qmp_port, qmp_loadvm_cmd)

        error_context.context("Execute 'guest-set-time' in qmp monitor")
        gagent.gagent.set_time()

        error_context.context(
            "Execute 'rtc-reset-reinjection' in qmp" " monitor, not for power platform",
            test.log.info,
        )
        if arch.ARCH not in ("ppc64", "ppc64le"):
            qmp_rtc_reset_cmd = params["qmp_rtc_reset_cmd"]
            run_qmp_cmd(qmp_port, qmp_rtc_reset_cmd)

        sleep_time = int(params.get("sleep_time", "600"))
        sleep_iteration_times = int(params.get("sleep_iteration_times", "3"))
        for i in range(1, sleep_iteration_times + 1):
            time.sleep(sleep_time)
            query_ntp_time()
    finally:
        cleanup()
