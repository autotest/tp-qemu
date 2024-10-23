import os
import time

from avocado.utils import process
from virttest import (
    data_dir,
    env_process,
    error_context,
    utils_misc,
    utils_net,
    utils_netperf,
)


@error_context.context_aware
def run(test, params, env):
    """
    Try to kill the guest after/during network stress in guest.
    1) Boot up VM and log VM with serial.
    For driver mode test:
    2) Unload network driver(s).
    3) Load network driver(s) again.
    4) Repeat step 2 and 3 for 50 times.
    5) Check that we can kill VM with signal 0.
    For load mode test:
    2) Stop iptables in guest and host.
    3) Setup run netperf server in host and guest.
    4) Start heavy network load host <=> guest by running netperf
       client in host and guest.
    5) During netperf running, Check that we can kill VM with signal 0.
    6) Clean up netperf server in host and guest.(guest may already killed)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_ethernet_driver(session):
        """
        Get driver of network cards.

        :param session: session to machine
        """
        modules = []
        cmd = params.get("nic_module_cmd")
        out = session.cmd(cmd)
        for module in out.split("\n"):
            if cmd not in module:
                modules.append(module.split("/")[-1])
        modules.remove("")
        return set(modules)

    def kill_and_check(test, vm):
        vm.destroy(gracefully=False)
        if not vm.wait_until_dead(timeout=60):
            test.fail("VM is not dead after destroy operation")
        test.log.info("VM is dead as expected")

    def netperf_stress(test, params, vm):
        """
        Netperf stress test.
        """
        n_client = utils_netperf.NetperfClient(
            vm.get_address(),
            params.get("client_path"),
            netperf_source=os.path.join(
                data_dir.get_deps_dir("netperf"), params.get("netperf_client_link")
            ),
            client=params.get("shell_client"),
            port=params.get("shell_port"),
            username=params.get("username"),
            password=params.get("password"),
            prompt=params.get("shell_prompt"),
            linesep=params.get("shell_linesep", "\n").encode().decode("unicode_escape"),
            status_test_command=params.get("status_test_command", ""),
            compile_option=params.get("compile_option", ""),
        )
        n_server = utils_netperf.NetperfServer(
            utils_net.get_host_ip_address(params),
            params.get("server_path", "/var/tmp"),
            netperf_source=os.path.join(
                data_dir.get_deps_dir("netperf"), params.get("netperf_server_link")
            ),
            password=params.get("hostpassword"),
            compile_option=params.get("compile_option", ""),
        )

        try:
            n_server.start()
            # Run netperf with message size defined in range.
            test_duration = params.get_numeric("netperf_test_duration")
            test_protocols = params.get("test_protocol")
            netperf_output_unit = params.get("netperf_output_unit")
            test_option = params.get("test_option", "")
            test_option += " -l %s" % test_duration
            if params.get("netperf_remote_cpu") == "yes":
                test_option += " -C"
            if params.get("netperf_local_cpu") == "yes":
                test_option += " -c"
            if netperf_output_unit in "GMKgmk":
                test_option += " -f %s" % netperf_output_unit
            t_option = "%s -t %s" % (test_option, test_protocols)
            n_client.bg_start(
                utils_net.get_host_ip_address(params),
                t_option,
                params.get_numeric("netperf_para_sessions"),
                params.get("netperf_cmd_prefix", ""),
                package_sizes=params.get("netperf_sizes"),
            )
            if utils_misc.wait_for(
                n_client.is_netperf_running, 10, 0, 1, "Wait netperf test start"
            ):
                test.log.info("Netperf test start successfully.")
            else:
                test.error("Can not start netperf client.")
        finally:
            n_server.stop()
            n_server.cleanup(True)
            n_client.cleanup(True)

    def netload_kill_problem(test, session_serial):
        firewall_flush = params.get("firewall_flush", "service iptables stop")
        error_context.context("Stop firewall in guest and host.", test.log.info)
        try:
            process.run(firewall_flush, shell=True)
        except Exception:
            test.log.warning("Could not stop firewall in host")

        try:
            session_serial.cmd(firewall_flush)
        except Exception:
            test.log.warning("Could not stop firewall in guest")

        try:
            error_context.context(
                ("Run subtest netperf_stress between" " host and guest.", test.log.info)
            )
            stress_thread = None
            wait_time = int(params.get("wait_bg_time", 60))
            bg_stress_run_flag = params.get("bg_stress_run_flag")
            vm_wait_time = int(params.get("wait_before_kill_vm"))
            env[bg_stress_run_flag] = False
            stress_thread = utils_misc.InterruptedThread(
                netperf_stress, (test, params, vm)
            )
            stress_thread.start()
            utils_misc.wait_for(
                lambda: wait_time, 0, 1, "Wait netperf_stress test start"
            )
            test.log.info("Sleep %ss before killing the VM", vm_wait_time)
            time.sleep(vm_wait_time)
            msg = "During netperf running, Check that we can kill VM with signal 0"
            error_context.context(msg, test.log.info)
            kill_and_check(test, vm)
        finally:
            try:
                stress_thread.join(60)
            except Exception:
                pass

    def netdriver_kill_problem(test, session_serial):
        times = params.get_numeric("repeat_times", 10)
        modules = get_ethernet_driver(session_serial)
        test.log.debug("Guest network driver(s): %s", modules)
        msg = "Repeatedly load/unload network driver(s) for %s times." % times
        error_context.context(msg, test.log.info)
        for i in range(times):
            for module in modules:
                error_context.context(
                    "Unload driver %s. Repeat: %s/%s" % (module, i, times)
                )
                session_serial.cmd_output_safe("rmmod %s" % module)
            for module in modules:
                error_context.context(
                    "Load driver %s. Repeat: %s/%s" % (module, i, times)
                )
                session_serial.cmd_output_safe("modprobe %s" % module)

        error_context.context("Check that we can kill VM with signal 0.", test.log.info)
        kill_and_check(test, vm)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = params.get_numeric("login_timeout", 360)
    session = vm.wait_for_login(timeout=login_timeout)
    session.close()
    session_serial = vm.wait_for_serial_login(timeout=login_timeout)
    mode = params.get("mode")
    if mode == "driver":
        netdriver_kill_problem(test, session_serial)
    elif mode == "load":
        netload_kill_problem(test, session_serial)
    session_serial.close()
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)
