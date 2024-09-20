import logging
import os
import time

import six
from avocado.utils import process
from virttest import remote, utils_misc, utils_net, utils_sriov

from provider import dpdk_utils

LOG_JOB = logging.getLogger("avocado.test")


def format_result(result, base, fbase):
    """
    Format the result to a fixed length string.

    :param result: result need to convert
    :param base: the length of converted string
    :param fbase: the decimal digit for float
    """

    if isinstance(result, six.string_types):
        value = "%" + base + "s"
    elif isinstance(result, int):
        value = "%" + base + "d"
    elif isinstance(result, float):
        value = "%" + base + "." + fbase + "f"
    else:
        raise TypeError(f"unexpected result type: {type(result).__name__}")
    return value % result


def run(test, params, env):
    """
    Run the DPDK test.

    1) Boot the vm
    2) Install DPDK on the guest (remote host) and load the necessary modules
    3) On the vm, bind the PCI device to vfio for DPDK usage
    4) Run the DPDK test based on the forward mode (txonly/rxonly)
    5) Collect and record the test results

    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    # get parameter from dictionary
    login_timeout = int(params.get("login_timeout", 360))
    forward_mode = params.get("forward_mode")
    params.get("device_type_guest")
    params.get("device_type_host")
    dpdk_pkts = params.get("dpdk_pkts")
    dpdk_queues = params.get("dpdk_queues")
    dpdk_tool_path = params.get("dpdk_tool_path")
    record_list = params.get("record_list")
    kvm_ver_chk_cmd = params.get("kvm_ver_chk_cmd")
    guest_ver_cmd = params["guest_ver_cmd"]
    base = params.get("format_base", "12")
    fbase = params.get("format_fbase", "2")

    session = vm.wait_for_login(timeout=login_timeout, restart_network=True)

    # get qemu, guest kernel and kvm version info and write them into result
    result_path = utils_misc.get_path(test.resultsdir, "dpdk.RHS")
    result_file = open(result_path, "w")
    kvm_ver = process.system_output(kvm_ver_chk_cmd, shell=True).decode()
    host_ver = os.uname()[2]
    guest_ver = session.cmd_output(guest_ver_cmd)
    result_file.write("### kvm-userspace-ver : %s\n" % kvm_ver)
    result_file.write("### kvm_version : %s\n" % host_ver)
    result_file.write("### guest-kernel-ver :%s" % guest_ver)

    dpdk_utils.install_dpdk(params, session)
    dpdk_ver = session.cmd_output("rpm -qa |grep dpdk | head -n 1")
    result_file.write("### guest-dpdk-ver :%s" % dpdk_ver)
    dpdk_utils.load_vfio_modules(session)

    # get record_list
    record_line = ""
    for record in record_list.split():
        record_line += "%s|" % format_result(record, base, fbase)

    for nic_index, nic in enumerate(vm.virtnet):
        if nic.nettype == "vdpa":
            mac = "0," + nic.mac
            ethname = utils_net.get_linux_ifname(session, nic.mac)
            pci_id = utils_sriov.get_pci_from_iface(ethname, session).strip()
    dpdk_utils.bind_pci_device_to_vfio(session, pci_id)  # pylint: disable=E0606

    guest = {
        "host": vm.get_address(),
        "username": params.get("username"),
        "password": params.get("password"),
        "cpu": session.cmd_output("nproc").strip(),
        "pci": pci_id,
    }

    host = None
    if "rxonly" in forward_mode.split():
        dsthost = params.get("dsthost")
        params_host = params.object_params("dsthost")
        dst_ses = remote.wait_for_login(
            params_host.get("shell_client"),
            dsthost,
            params_host.get("shell_port"),
            params_host.get("username"),
            params_host.get("password"),
            params_host.get("shell_prompt"),
            timeout=login_timeout,
        )
        host = {
            "host": dsthost,
            "username": params_host.get("unsername"),
            "password": params_host.get("password"),
            "cpu": dst_ses.cmd_output(("nproc").strip()),
            "pci": params_host.get("dsthost_pci"),
        }
        dpdk_utils.install_dpdk(params, dst_ses)

    for forward in forward_mode.split():
        result_file.write("Category:%s\n" % forward)
        result_file.write("%s\n" % record_line.rstrip("|"))
        for pkts in dpdk_pkts.split():
            for queue in dpdk_queues.split():
                LOG_JOB.info(
                    "Processing dpdk test with forward mode: %s, pkts: %s, queue: %s",
                    forward,
                    pkts,
                    queue,
                )
                pps = run_test(
                    forward,
                    guest,
                    host if forward == "rxonly" else None,
                    dpdk_tool_path,
                    queue,
                    pkts,
                    mac if forward == "rxonly" else None,  # pylint: disable=E0606
                )
                time.sleep(2)
                mpps = "%.2f" % (float(pps) / (10**6))
                line = "%s|" % format_result(pkts, base, fbase)
                line += "%s|" % format_result(queue, base, fbase)
                line += "%s|" % format_result(pps, base, fbase)
                line += "%s|" % format_result(mpps, base, fbase)
                result_file.write(("%s\n" % line))

    result_file.close()
    session.close()


def run_test(forward_mode, guest, host, dpdk_tool_path, queue, pkts, mac=None):
    """
    Run the DPDK test for a specific forward mode.

    :param forward_mode: Forward mode (txonly/rxonly)
    :param guest: Dictionary containing guest details
    :param host: Dictionary containing host details
    :param dpdk_tool_path: Path to the DPDK tool
    :param queue: Queue number
    :param pkts: Number of packets
    :param mac: MAC address (optional)
    :return: pps value
    """

    if forward_mode == "txonly":
        testpmd_guest = dpdk_utils.TestPMD(
            guest["host"], guest["username"], guest["password"]
        )

    elif forward_mode == "rxonly":
        testpmd_host = dpdk_utils.TestPMD(
            host["host"], host["username"], host["password"]
        )
        testpmd_host.login()
        testpmd_host.launch_testpmd(
            dpdk_tool_path, host["cpu"], host["pci"], "txonly", 16, pkts, mac=mac
        )
        testpmd_host.show_port_stats_all()
        testpmd_host.show_port_stats_all()
        time.sleep(2)

    testpmd_guest = dpdk_utils.TestPMD(
        guest["host"], guest["username"], guest["password"]
    )

    testpmd_guest.login()
    testpmd_guest.launch_testpmd(
        dpdk_tool_path, guest["cpu"], guest["pci"], forward_mode, queue, pkts
    )
    testpmd_guest.show_port_stats_all()
    output = testpmd_guest.show_port_stats_all()
    pps_value = testpmd_guest.extract_pps_value(output, forward_mode)

    if forward_mode == "rxonly":
        testpmd_host.quit_testpmd()
        testpmd_host.logout()
    testpmd_guest.quit_testpmd()
    testpmd_guest.logout()

    return pps_value
