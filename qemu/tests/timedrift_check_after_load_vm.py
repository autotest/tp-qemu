import re
import time
import logging

from avocado.utils import process
from virttest import env_process
from virttest import error_context
from virttest import guest_agent
from virttest import arch


@error_context.context_aware
def run(test, params, env):
    """
    Clock check after savevm and loadvm
    Note: Run this test case, make sure that guest agent is installed
    and start inside the guest.

    1. On host, load kvm module with "kvmclock_periodic_sync=N"
    2. On host, sync time with ntp server
    2. Boot guest with qemu guest agent
    3. On guest, sync time with ntp server
    4. On guest, stop chronyd
    5. Run samevm and loadvm
    6. Run qemu-guest-agent command: guest-set-time
    7. Run qmp command: rtc-reset-reinjection
    8. On guest, query the time offset with ntp server,
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
        error_context.context("_load_kvm_module_with_kvmclock_periodic_sync=%s"
                              % module_param, logging.info)
        check_modules = arch.get_kvm_module_list()
        error_context.context("check_module: '%s'" % check_modules, logging.info)
        check_modules.reverse()
        for module in check_modules:
            rm_mod_cmd = "modprobe -r %s" % module
            process.system(rm_mod_cmd, shell=True)
        check_modules.reverse()
        for module in check_modules:
            load_mod_cmd = "modprobe %s" % module
            if module == "kvm":
                load_mod_cmd = "%s kvmclock_periodic_sync=%s" % (load_mod_cmd, module_param)
            process.system(load_mod_cmd, shell=True)
        check_mod_cmd = params["check_mod_cmd"]
        if process.system_output(check_mod_cmd) != module_param:
            test.fail("Cannot load kvm module with kvmclock_periodic_sync=%s"
                      % module_param)

    def setup():
        """
        On host, load kvm module with "kvmclock_periodic_sync=N"
        sync time with ntp server and boot the guest
        """
        _load_kvm_module_with_kvmclock_periodic_sync("N")
        error_context.context("Sync host time with ntp server", logging.info)
        host_ntp_cmd = params["host_ntp_cmd"]
        process.system(host_ntp_cmd, shell=True)

        error_context.context("Boot the guest", logging.info)
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
        _load_kvm_module_with_kvmclock_periodic_sync("Y")

    def create_gagent():
        """
        Create a QemuAgent object to send guest agent command
        """
        gagent_serial_type = params["gagent_serial_type"]
        gagent_name = params["gagent_name"]
        if gagent_serial_type == guest_agent.QemuAgent.SERIAL_TYPE_VIRTIO:
            filename = vm.get_virtio_port_filename(gagent_name)
        elif gagent_serial_type == guest_agent.QemuAgent.SERIAL_TYPE_ISA:
            filename = vm.get_serial_console_filename(gagent_name)
        else:
            raise guest_agent.VAgentNotSupportedError("Not supported serial"
                                                      "type")
        return guest_agent.QemuAgent(vm, gagent_name, gagent_serial_type,
                                     filename, get_supported_cmds=True)

    def run_qmp_cmd(qmp_port, qmp_cmd):
        """
        Run a qmp command

        :params qmp_port: the guest qmp port to send qmp command
        :params qmp_cmd: qmp command
        """
        output = qmp_port.send_args_cmd(qmp_cmd)
        error_context.context("QMP command: '%s' \n Output: '%s'"
                              % (qmp_cmd, output), logging.info)

    def query_ntp_time():
        """
        On guest, use "ntpdate -q {ntp_server}" to query the clock offset
        """
        ntp_query_cmd = params["ntp_query_cmd"]
        output = session.cmd_output_safe(ntp_query_cmd)
        error_context.context("Command: '%s'  \n Output: '%s'"
                              % (ntp_query_cmd, output), logging.info)
        offset = float(re.findall(r"[offset|+|-]\s*(\d+\.\d+)", output)[-1])
        error_context.context("offset: '%.2f'" % offset, logging.info)
        exptectd_time_drift = params.get("expected_time_drift", 3)
        if offset > float(exptectd_time_drift):
            test.fail("After loadvm, the time drift of guest is too large.")

    vm = setup()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    try:
        error_context.context("Sync guest time with ntp server", logging.info)
        ntp_cmd = params["ntp_cmd"]
        output = session.cmd_output_safe(ntp_cmd)
        error_context.context("Command: '%s'  \n Output: '%s'"
                              % (ntp_cmd, output), logging.info)

        qmp_ports = vm.get_monitors_by_type('qmp')
        if qmp_ports:
            qmp_port = qmp_ports[0]
        else:
            test.fail("Incorrect configuration, no QMP monitor found.")
        stop_chronyd_cmd = params["stop_chronyd_cmd"]
        process.system_output(stop_chronyd_cmd, shell=True)
        qmp_savevm_cmd = params["qmp_savevm_cmd"]
        run_qmp_cmd(qmp_port, qmp_savevm_cmd)
        qmp_loadvm_cmd = params["qmp_loadvm_cmd"]
        run_qmp_cmd(qmp_port, qmp_loadvm_cmd)

        gagent = create_gagent()
        gagent.set_time()
        qmp_rtc_reset_cmd = params["qmp_rtc_reset_cmd"]
        run_qmp_cmd = (qmp_port, qmp_rtc_reset_cmd)

        sleep_time = int(params.get("sleep_time", "600"))
        sleep_iteration_times = int(params.get("sleep_iteration_times", "3"))
        for i in xrange(1, sleep_iteration_times + 1):
            time.sleep(sleep_time)
            query_ntp_time()
    finally:
        cleanup()
