import logging
import time

from avocado.utils import process
from virttest import utils_misc
from virttest import env_process
from virttest import error_context

from provider import netperf_test


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
        logging.info("VM is dead as expected")

    def netload_kill_problem(test, session_serial):
        firewall_flush = params.get("firewall_flush", "service iptables stop")
        error_context.context("Stop firewall in guest and host.", logging.info)
        try:
            process.run(firewall_flush, shell=True)
        except Exception:
            logging.warning("Could not stop firewall in host")

        try:
            session_serial.cmd(firewall_flush)
        except Exception:
            logging.warning("Could not stop firewall in guest")

        try:
            error_context.context(("Run subtest netperf_stress between"
                                   " host and guest.", logging.info))
            stress_thread = None
            wait_time = int(params.get("wait_bg_time", 60))
            bg_stress_run_flag = params.get("bg_stress_run_flag")
            vm_wait_time = int(params.get("wait_before_kill_vm"))
            env[bg_stress_run_flag] = False
            stress_thread = utils_misc.InterruptedThread(
                netperf_test.netperf_stress, (test, params, vm))
            stress_thread.start()
            utils_misc.wait_for(lambda: wait_time, 0, 1,
                                "Wait netperf_stress test start")
            logging.info("Sleep %ss before killing the VM", vm_wait_time)
            time.sleep(vm_wait_time)
            msg = "During netperf running, Check that we can kill VM with signal 0"
            error_context.context(msg, logging.info)
            kill_and_check(test, vm)
        finally:
            try:
                stress_thread.join(60)
            except Exception:
                pass

    def netdriver_kill_problem(test, session_serial):
        times = params.get_numeric("repeat_times", 10)
        modules = get_ethernet_driver(session_serial)
        logging.debug("Guest network driver(s): %s", modules)
        msg = "Repeatedly load/unload network driver(s) for %s times." % times
        error_context.context(msg, logging.info)
        for i in range(times):
            for module in modules:
                error_context.context("Unload driver %s. Repeat: %s/%s" %
                                      (module, i, times))
                session_serial.cmd_output_safe("rmmod %s" % module)
            for module in modules:
                error_context.context("Load driver %s. Repeat: %s/%s" %
                                      (module, i, times))
                session_serial.cmd_output_safe("modprobe %s" % module)

        error_context.context("Check that we can kill VM with signal 0.",
                              logging.info)
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
