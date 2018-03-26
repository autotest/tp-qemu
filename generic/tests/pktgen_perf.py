import logging
import os
import aexpect

from avocado.utils import process

from virttest import data_dir
from virttest import utils_net
from virttest import utils_test
from virttest import utils_misc
from virttest import error_context


def format_result(result, base="12", fbase="2"):
    """
    Format the result to a fixed length string.

    :param result: result need to convert
    :param base: the length of converted string
    :param fbase: the decimal digit for float
    """
    if isinstance(result, str):
        value = "%" + base + "s"
    elif isinstance(result, int):
        value = "%" + base + "d"
    elif isinstance(result, float):
        value = "%" + base + "." + fbase + "f"
    return value % result


@error_context.context_aware
def run(test, params, env):
    """
    Run Pktgen test between host/guest

    1) Boot the main vm, or just grab it if it's already booted.
    2) Configure pktgen on guest or host
    3) Run pktgen test, finish when timeout

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _pin_vm_threads(node):
        """
        pin guest vcpu and vhost threads to cpus of a numa node repectively

        :param node: which numa node to pin
        """
        if node:
            if not isinstance(node, utils_misc.NumaNode):
                node = utils_misc.NumaNode(int(node))
            utils_test.qemu.pin_vm_threads(vm, node)

    timeout = float(params.get("pktgen_test_timeout", "240"))
    run_threads = params.get("pktgen_threads", 1)
    record_list = params.get("record_list")
    error_context.context("Init the VM, and try to login", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    session_serial = vm.wait_for_serial_login()

    # print numa information on host and pinning vhost and vcpus to cpus
    process.system_output("numactl --hardware")
    process.system_output("numactl --show")
    _pin_vm_threads(params.get("numa_node"))

    # get parameter from dictionary
    category = params.get("category")
    pkt_size = params.get("pkt_size")
    kvm_ver_chk_cmd = params.get("kvm_ver_chk_cmd")
    guest_ver_cmd = params["guest_ver_cmd"]

    # get qemu, guest kernel and kvm version info and write them into result
    result_path = utils_misc.get_path(test.resultsdir, "pktgen_perf.RHS")
    result_file = open(result_path, "w")
    kvm_ver = process.system_output(kvm_ver_chk_cmd, shell=True)
    host_ver = os.uname()[2]
    guest_ver = session.cmd_output(guest_ver_cmd, timeout)
    result_file.write("### kvm-userspace-ver : %s\n" % kvm_ver)
    result_file.write("### kvm_version : %s\n" % host_ver)
    result_file.write("### guest-kernel-ver :%s\n" % guest_ver)

    # get record_list
    record_line = ""
    for record in record_list.split():
        record_line += "%s|" % format_result(record)

    # get result tested by each scenario
    for pkt_cate in category.split():
        result_file.write("Category:%s\n" % pkt_cate)
        result_file.write("%s\n" % record_line.rstrip("|"))

        # copy pktgen_test script to test server
        local_path = os.path.join(data_dir.get_shared_dir(),
                                  "scripts/pktgen_perf.sh")
        remote_path = "/tmp/pktgen_perf.sh"
        if pkt_cate == "tx":
            vm.copy_files_to(local_path, remote_path)
        elif pkt_cate == "rx":
            process.run("cp %s %s" % (local_path, remote_path))

        for size in pkt_size.split():
            if pkt_cate == "tx":
                error_context.context("test guest tx pps performance",
                                      logging.info)
                guest_mac = vm.get_mac_address(0)
                pktgen_interface = utils_net.get_linux_ifname(session,
                                                              guest_mac)
                dsc_dev = utils_net.Interface(vm.get_ifname(0))
                dsc = dsc_dev.get_mac()
                runner = session.cmd
                pktgen_ip = vm.wait_for_get_address(0, timeout=5)
                pkt_cate_r = run_test(session_serial, runner, remote_path,
                                      pktgen_ip, dsc, pktgen_interface,
                                      run_threads, size, timeout)
            elif pkt_cate == "rx":
                error_context.context("test guest rx pps performance",
                                      logging.info)
                host_bridge = params.get("netdst", "switch")
                host_nic = utils_net.Interface(host_bridge)
                pktgen_ip = host_nic.get_ip()
                dsc = vm.wait_for_get_address(0, timeout=5)
                pktgen_interface = vm.get_ifname(0)
                runner = process.system_output
                pkt_cate_r = run_test(session_serial, runner, remote_path,
                                      pktgen_ip, dsc, pktgen_interface,
                                      run_threads, size, timeout)
            line = "%s|" % format_result(size)
            line += "%s" % format_result(pkt_cate_r)
            result_file.write(("%s\n" % line))

    error_context.context("Verify Host and guest kernel no error\
                           and call trace", logging.info)
    vm.verify_kernel_crash()
    utils_misc.verify_dmesg()
    result_file.close()
    session_serial.close()
    session.close()


def run_test(session_serial, runner, remote_path, pktgen_ip, dsc,
             interface, run_threads, size, timeout):
    """
    Run pktgen_perf script on remote and gather packet numbers/time and
    calculate mpps.

    :param session_serial: session serial for vm.
    :param runner: connection for vm or host.
    :param remote_path: pktgen_perf script path.
    :param pktgen_ip: ip address which pktgen script was running.
    :param dsc: dsc mac or dsc ip pass to pktgen_perf script.
    :param interface: device name pass to pktgen_perf script.
    :param run_threads: the numbers pktgen threads.
    :param size: packet size pass to pktgen_perf script.
    :param timeout: test run time.
    """
    exec_cmd = "%s %s %s %s %s" % (remote_path, dsc, interface,
                                   run_threads, size)
    packets = "cat /sys/class/net/%s/statistics/tx_packets" % interface
    logging.info("Start pktgen test by cmd '%s'" % exec_cmd)
    try:
        packet_b = runner(packets)
        runner(exec_cmd, timeout)
    except aexpect.ShellTimeoutError:
        # when pktgen script is running on guest, it's damaged,
        # guest could not response by ssh, so uses serial instead.
        packet_a = session_serial.cmd(packets, timeout)
        kill_cmd = "kill -9 `ps -C pktgen_perf.sh -o pid=`"
        session_serial.cmd(kill_cmd)
        session_serial.cmd("ping %s -c 5" % pktgen_ip, ignore_all_errors=True)
    except process.CmdError:
        # when pktgen script is running on host, the pktgen process
        # will be quit when timeout trigger, so no need to kill it.
        packet_a = runner(packets)
        runner("ping %s -c 5" % pktgen_ip)
    count = int(packet_a) - int(packet_b)
    pps_results = count / timeout

    # conver pps to mpps
    power = 10**6
    mpps_results = float(pps_results) / float(power)
    mpps_results = "%.2f" % mpps_results
    return mpps_results
