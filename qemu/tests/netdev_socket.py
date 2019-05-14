import logging

from virttest import utils_net
from virttest import error_context
from virttest import env_process
from virttest import utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Test netdev socket

    1) Start two guests, one with listen, the other with connect
    2) Set static IP in the guests
    3) Do ping test between guests

    :param test: KVM test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    params["start_vm"] = 'yes'
    params["vhost"] = 'None'
    params["enable_vhostfd"] = "no"
    params["enable_msix_vectors"] = "no"
    params["nettype"] = "socket"
    login_timeout = int(params.get("login_timeout", "600"))
    vm_names = params.get("vms").split()
    vms_info = {}
    ping_count = int(params.get("ping_count", "10"))
    os_type = params["os_type"]
    if os_type == "linux":
        stop_NM_cmd = params["stop_NM_cmd"]

    try:
        for vm_name in vm_names:
            env_process.preprocess_vm(test, params, env, vm_name)
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            ip = params["ip_%s" % vm_name]
            mac = vm.get_mac_address()
            session = vm.wait_for_serial_login(timeout=login_timeout)
            if os_type == "linux":
                session.cmd(stop_NM_cmd, ignore_all_errors=True)
            utils_net.set_guest_ip_addr(session, mac, ip, os_type=os_type)
            vms_info[vm_name] = [vm, ip, session]

        logging.info("Ping %s from %s", vms_info[vm_names[1]][1],
                     vms_info[vm_names[0]][1])

        status, output = utils_test.ping(vms_info[vm_names[1]][1], ping_count,
                                         timeout=float(ping_count) * 1.5,
                                         session=vms_info[vm_names[0]][2])
        if status != 0:
            test.fail("Ping returns non-zero value %s" % output)
        package_lost = utils_test.get_loss_ratio(output)
        if package_lost != 0:
            test.fail("%s packeage lost when ping guest ip %s " %
                      (package_lost, vms_info[vm_names[1]][1]))
    finally:
        for vm in vm_names:
            vms_info[vm][2].close()
            vms_info[vm][0].destroy(gracefully=False)
