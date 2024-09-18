import logging
import re
import threading
import time

from avocado.utils import process
from virttest import error_context, utils_misc, utils_test

LOG_JOB = logging.getLogger("avocado.test")


def _check_cpu_usage(session):
    """
    Check windows guest cpu usage by wmic. This function is used within
    utils_misc.wait_for(), to check cpu usage repeatedly.

    param session: a session object to send wmic commands
    """
    status, output = session.cmd_status_output("wmic cpu get loadpercentage /value")
    if not status:
        result = re.search(r"LoadPercentage=(\d+)", output)
        if result:
            percent = int(result.group(1))
            if percent > 1:
                LOG_JOB.warning("Guest cpu usage :%s%%", percent)


def _check_cpu_thread_func(session, timeout):
    """
    Repeatedlly checking guest cpu usage, until timeout has arrived.

    param session: a session object to send commands
    param timeout: total checking time
    """
    utils_misc.wait_for(lambda: _check_cpu_usage(session), timeout, 0, 5)


def _pin_vm_threads(vm, node):
    """
    Pin guest to certain numa node.

    param vm: a vm object
    param node: a numa node to pin to
    """
    node = utils_misc.NumaNode(node)
    utils_test.qemu.pin_vm_threads(vm, node)


def _stop_service(test, params, session, service):
    """
    Check & stop windows system service

    param session: a session to send commands
    param service: the name of the service to stop
    """
    service_check_cmd = params.get("service_check_cmd")
    service_stop_cmd = params.get("service_stop_cmd")
    s, o = session.cmd_status_output("sc query")
    if s:
        test.error("Failed to query service list, " "status=%s, output=%s" % (s, o))
    service_item = re.search(r"SERVICE_NAME:\s+%s" % service, o, re.I | re.M)
    if not service_item:
        return

    s, o = session.cmd_status_output(service_check_cmd % service)
    if s:
        test.error(
            "Failed to get status for service: %s, "
            "status=%s, output=%s" % (service, s, o)
        )
    if re.search(r"STOPPED", o, re.I | re.M):
        return
    session.cmd(service_stop_cmd.format(service))


@error_context.context_aware
def run(test, params, env):
    """
    Cpu utilization test with hv flags.

    1)Start a Windows guest vm.
    2)Pin the vm to certain numa node, to keep accuracy.
    3)Stop serval Windows services & background processes on guest.
      to lower the cpu usage to minimum.
    4)Reboot vm to apply changes, then wait for serveral minutes to make
      sure the cpu is chill down.
    5)Start both checking the guest&host's cpu usage, monitoring the value.
    6)Compare the average utilization value to standard values.

    param test: the test object
    param params: the params of the test
    param env: the testing environment object
    """
    vm = env.get_vm(params["main_vm"])

    # pin guest vcpus/memory/vhost threads to last numa node of host
    _pin_vm_threads(vm, params.get_numeric("numa_node", -1))

    vm.verify_alive()

    timeout = params.get_numeric("login_timeout", 240)
    host_check_times = params.get_numeric("host_check_times", 900)
    host_check_interval = params.get_numeric("host_check_interval", 2)
    guest_check_timeout = host_check_times * host_check_interval
    thread_cpu_level = params.get_numeric("thread_cpu_level", 5)
    set_owner_cmd = params.get("set_owner_cmd")
    set_full_control_cmd = params.get("set_full_control_cmd")
    session = vm.wait_for_serial_login(timeout=timeout)
    do_migration = params.get("do_migration", "no") == "yes"

    service_names = params.get("serives_to_stop").split()

    # check and stop services
    for service in service_names:
        _stop_service(test, params, session, service)

    # stop windows defender
    if set_owner_cmd and set_full_control_cmd:
        set_owner_cmd = utils_misc.set_winutils_letter(session, set_owner_cmd)
        set_full_control_cmd = utils_misc.set_winutils_letter(
            session, set_full_control_cmd
        )
        session.cmd(set_owner_cmd)
        session.cmd(set_full_control_cmd)
    session.cmd(params["reg_cmd"])

    session = vm.reboot(session, timeout=timeout, serial=True)

    if do_migration:
        vm.migrate(env=env)
        session = vm.wait_for_serial_login(timeout=timeout)

    # wait for the guest to chill
    time.sleep(1800)

    # start background checking guest cpu usage
    thread = threading.Thread(
        target=_check_cpu_thread_func, args=(session, guest_check_timeout)
    )
    thread.start()
    time.sleep(60)

    # start checking host cpu usage
    pid = vm.get_pid()
    process.system(params["host_check_cmd"] % pid, shell=True)
    thread.join(guest_check_timeout + 360)

    vcpu_thread_pattern = params.get("vcpu_thread_pattern", r"thread_id.?[:|=]\s*(\d+)")
    vcpu_ids = vm.get_vcpu_pids(vcpu_thread_pattern)
    for thread_id in vcpu_ids:
        # output result
        host_cpu_usage = process.system_output(
            params["thread_process_cmd"] % thread_id, shell=True
        )
        host_cpu_usage = float(host_cpu_usage.decode())
        if host_cpu_usage > thread_cpu_level:
            test.fail(
                "The cpu usage of thread %s is %s"
                " > %s" % (thread_id, host_cpu_usage, thread_cpu_level)
            )
