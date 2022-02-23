import logging
import os
import six
import aexpect
import functools
import re

from avocado.utils import process

from virttest import data_dir
from virttest import utils_net
from virttest import utils_test
from virttest import utils_misc
from virttest import error_context

LOG_JOB = logging.getLogger('avocado.test')

_system_output = functools.partial(process.system_output, shell=True)


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
    error_context.context("Init the VM, and try to login", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session_serial = vm.wait_for_serial_login(restart_network=True)
    session = vm.wait_for_login()

    # print numa information on host and pinning vhost and vcpus to cpus
    process.system_output("numactl --hardware")
    process.system_output("numactl --show")
    _pin_vm_threads(params.get("numa_node"))

    # get parameter from dictionary
    category = params.get("category")
    pkt_size = params.get("pkt_size")
    run_threads = params.get("pktgen_threads")
    burst = params.get("burst")
    record_list = params.get("record_list")
    pktgen_script = params.get('pktgen_script')
    kvm_ver_chk_cmd = params.get("kvm_ver_chk_cmd")
    guest_ver_cmd = params["guest_ver_cmd"]
    base = params.get("format_base", "12")
    fbase = params.get("format_fbase", "2")

    # get qemu, guest kernel and kvm version info and write them into result
    result_path = utils_misc.get_path(test.resultsdir, "pktgen_perf.RHS")
    result_file = open(result_path, "w")
    kvm_ver = process.system_output(kvm_ver_chk_cmd, shell=True).decode()
    host_ver = os.uname()[2]
    guest_ver = session.cmd_output(guest_ver_cmd, timeout)
    result_file.write("### kvm-userspace-ver : %s\n" % kvm_ver)
    result_file.write("### kvm_version : %s\n" % host_ver)
    result_file.write("### guest-kernel-ver :%s" % guest_ver)

    # get record_list
    record_line = ""
    for record in record_list.split():
        record_line += "%s|" % format_result(record, base, fbase)

    def install_package(ver, session=None):
        """ check module pktgen, install kernel-modules-internal package """

        output_cmd = _system_output
        kernel_ver = "kernel-modules-internal-%s" % ver
        cmd_download = "cd /tmp && brew download-build %s --rpm" % kernel_ver
        cmd_install = "cd /tmp && rpm -ivh  %s.rpm --force --nodeps" % kernel_ver
        output_cmd(cmd_download).decode()
        cmd_clean = "rm -rf /tmp/%s.rpm" % kernel_ver
        if session:
            output_cmd = session.cmd_output
            local_path = "/tmp/%s.rpm" % kernel_ver
            remote_path = "/tmp/"
            vm.copy_files_to(local_path, remote_path)
        output_cmd(cmd_install)
        output_cmd(cmd_clean)

    def is_version_lt_rhel7(uname_str):
        ver = re.findall('el(\\d)', uname_str)
        if ver:
            return int(ver[0]) > 7
        return False

    if is_version_lt_rhel7(process.getoutput('uname -r')):
        install_package(host_ver)
    if is_version_lt_rhel7(session.cmd('uname -r')):
        install_package(guest_ver.strip(), session=session)

    # get result tested by each scenario
    pktgen_script = params.get('pktgen_script')
    for pktgen_script in pktgen_script.split():

        # copy pktgen_test script to test server
        local_path = os.path.join(data_dir.get_shared_dir(),
                                  "scripts/pktgen_perf")
        remote_path = "/tmp/"
        for pkt_cate in category.split():
            result_file.write("Script:%s " % pktgen_script)
            result_file.write("Category:%s\n" % pkt_cate)
            result_file.write("%s\n" % record_line.rstrip("|"))

            if pkt_cate == "tx":
                vm.copy_files_to(local_path, remote_path)
            elif pkt_cate == "rx":
                process.run("cp -r %s %s" % (local_path, remote_path))

            for size in pkt_size.split():
                for threads in run_threads.split():
                    for burst in burst.split():
                        if pkt_cate == "tx":
                            error_context.context("test guest tx pps"
                                                  " performance",
                                                  test.log.info)
                            guest_mac = vm.get_mac_address(0)
                            pktgen_interface = utils_net.get_linux_ifname(
                                               session, guest_mac)
                            dsc_dev = utils_net.Interface(vm.get_ifname(0))
                            dsc = dsc_dev.get_mac()
                            runner = session.cmd
                            pktgen_ip = vm.wait_for_get_address(0, timeout=5)
                        elif pkt_cate == "rx":
                            error_context.context("test guest rx pps"
                                                  " performance",
                                                  test.log.info)
                            host_bridge = params.get("netdst", "switch")
                            host_nic = utils_net.Interface(host_bridge)
                            pktgen_ip = host_nic.get_ip()
                            if pktgen_script == "pktgen_perf":
                                dsc = vm.wait_for_get_address(0, timeout=5)
                            else:
                                dsc = vm.get_mac_address(0)
                            pktgen_interface = vm.get_ifname(0)
                            runner = _system_output
                        pkt_cate_r = run_test(session_serial, runner,
                                              pktgen_script, pkt_cate,
                                              pktgen_ip, pktgen_interface,
                                              dsc, threads, size, burst,
                                              timeout)
                        line = "%s|" % format_result(size, base, fbase)
                        line += "%s|" % format_result(threads, base, fbase)
                        line += "%s|" % format_result(burst, base, fbase)
                        line += "%s" % format_result(pkt_cate_r, base, fbase)
                        result_file.write(("%s\n" % line))

    error_context.context("Verify Host and guest kernel no error\
                           and call trace", test.log.info)
    vm.verify_kernel_crash()
    utils_misc.verify_dmesg()
    result_file.close()
    session_serial.close()
    session.close()


def run_test(session_serial, runner, pktgen_script, pkt_rate, pktgen_ip,
             interface, dsc, threads, size, burst, timeout):
    """
    Run pktgen_perf script on remote and gather packet numbers/time and
    calculate mpps.

    :param session_serial: session serial for vm.
    :param runner: connection for vm or host.
    :param pktgen_script: pktgen script name.
    :param pkt_rate: tx or rx category.
    :param pktgen_ip: ip address which pktgen script was running.
    :param interface: device name pass to pktgen_perf script.
    :param dsc: dsc mac or dsc ip pass to pktgen_perf script.
    :param threads: the numbers pktgen threads.
    :param size: packet size pass to pktgen_perf script.
    :param burst: HW level bursting of SKBs.
    :param timeout: test run time.
    """

    pktgen_script_path = "/tmp/pktgen_perf/%s.sh" % pktgen_script
    if pktgen_script in "pktgen_perf":
        dsc_option = '-m' if pkt_rate == 'tx' else '-d'
        exec_cmd = "%s -i %s %s %s -t %s -s %s" % (
                pktgen_script_path, interface, dsc_option, dsc, threads, size)
    else:
        exec_cmd = "%s -i %s -m %s -n 0 -t %s -s %s -b %s -c 0" % (
                pktgen_script_path, interface, dsc, threads, size, burst)
    packets = "cat /sys/class/net/%s/statistics/tx_packets" % interface
    LOG_JOB.info("Start pktgen test by cmd '%s'", exec_cmd)
    try:
        packet_b = runner(packets)
        runner(exec_cmd, timeout)
    except aexpect.ShellTimeoutError:
        # when pktgen script is running on guest, it's damaged,
        # guest could not response by ssh, so uses serial instead.
        packet_a = session_serial.cmd(packets, timeout)
        kill_cmd = "kill -9 `ps -ef | grep %s --color | grep -v grep | "\
                   "awk '{print $2}'`" % pktgen_script
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
