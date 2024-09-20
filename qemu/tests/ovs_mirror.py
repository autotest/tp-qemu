import glob
import os
import re
import shutil
import time

from avocado.utils import path as utils_path
from avocado.utils import process
from virttest import env_process, error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Test port mirror between guests in one ovs backend

    1) Boot the three vms.
    2) Set tap device of vm1 to mirror (input, output, input & output)
       of tap device of vm2 in openvswith.
    3) Start two tcpdump threads to dump icmp packet from vm2 and vm3.
    4) Ping host from vm2 and vm3.
    5) Stop ping in vm2 and vm3
    6) Check tcmpdump result in vm1.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def make_mirror_cmd(mirror_port, target_port, direction="all", ovs="ovs0"):
        """
        Generate create ovs port mirror command.

        :parm mirror_port: port name in ovs in mirror status.
        :parm target_port: port name in ovs be mirroring.
        :parm direction: mirror direction, all, only input or output.
        :parm ovs: ovs port name.

        :return: string of ovs port mirror command.
        """
        cmd = ["ovs-vsctl set Bridge %s mirrors=@m " % ovs]
        for port in [mirror_port, target_port]:
            cmd.append("-- --id=@%s get Port %s " % (port, port))
        if direction == "input":
            cmd.append("-- --id=@m create Mirror name=input_of_%s" % target_port)
            cmd.append("select-dst-port=@%s" % target_port)
        elif direction == "output":
            cmd.append("-- --id=@m create Mirror name=output_of_%s" % target_port)
            cmd.append("select-src-port=@%s" % target_port)
        else:
            cmd.append("-- --id=@m create Mirror name=mirror_%s" % target_port)
            cmd.append("select-src-port=@%s" % target_port)
            cmd.append("select-dst-port=@%s" % target_port)
        cmd.append("output-port=@%s" % mirror_port)
        return " ".join(cmd)

    def create_mirror_port(mirror_port, target_port, direction, ovs):
        """
        Execute ovs port mirror command and check port really in mirror status.

        :parm mirror_port: port name in ovs in mirror status.
        :parm target_port: port name in ovs be mirroring.
        :parm direction: mirror direction, all, only input or output.
        :parm ovs: ovs port name.
        """
        mirror_cmd = make_mirror_cmd(mirror_port, target_port, direction, ovs)
        uuid = process.system_output(mirror_cmd)
        output = process.system_output("ovs-vsctl list mirror")
        if uuid not in output:
            test.log.debug("Create OVS Mirror CMD: %s ", mirror_cmd)
            test.log.debug("Ovs Info: %s ", output)
            test.fail("Setup mirorr port failed")

    def check_tcpdump(output, target_ip, host_ip, direction):
        """
        Check tcpdump result file and report unexpect packet to debug log.

        :parm output: string of tcpdump output.
        :parm target_p: ip of port in ovs be mirroring.
        :parm host_ip: ip of ovs port.
        :parm direction: mirror direction, all, only input or output.

        :return: bool type result.
        """
        rex = r".*IP (%s|%s) > " % (host_ip, target_ip)
        rex += "(%s|%s).*ICMP echo.*" % (target_ip, host_ip)
        if direction == "input":
            rex = r".*IP %s > %s.*ICMP echo reply.*" % (host_ip, target_ip)
        if direction == "output":
            rex = r".*IP %s > %s.*ICMP echo request.*" % (target_ip, host_ip)
        for idx, _ in enumerate(output.splitlines()):
            if not re.match(rex, _):
                test.log.debug("Unexpect packet in line %d: %s", idx, _)
                return False
        return True

    utils_path.find_command("ovs-vsctl")
    ovs_name = params.get("ovs_name", "ovs0")
    direction = params.get("direction", "all")
    mirror_vm = params.get("mirror_vm", "vm1")
    target_vm = params.get("target_vm", "vm2")
    refer_vm = params.get("refer_vm", "vm3")
    net_mask = params.get("net_mask", "24")
    host_ip = params.get("ip_ovs", "192.168.1.1")
    pre_guest_cmd = params.get("pre_guest_cmd")
    ovs_create_cmd = params.get("ovs_create_cmd")
    ovs_remove_cmd = params.get("ovs_remove_cmd")
    login_timeout = int(params.get("login_timeout", "600"))

    error_context.context("Create private ovs switch", test.log.info)
    process.system(ovs_create_cmd, shell=True)
    params["start_vm"] = "yes"
    params["netdst"] = ovs_name
    vms_info = {}
    try:
        for p_vm in params.get("vms").split():
            env_process.preprocess_vm(test, params, env, p_vm)
            o_vm = env.get_vm(p_vm)
            o_vm.verify_alive()
            ip = params["ip_%s" % p_vm]
            mac = o_vm.get_mac_address()
            ses = o_vm.wait_for_serial_login(timeout=login_timeout)
            ses.cmd(pre_guest_cmd)
            nic_name = utils_net.get_linux_ifname(ses, mac)
            ifname = o_vm.get_ifname()
            vms_info[p_vm] = [o_vm, ifname, ip, ses, nic_name]

        mirror_ifname = vms_info[mirror_vm][1]
        mirror_ip = vms_info[mirror_vm][2]
        mirror_nic = vms_info[mirror_vm][4]
        target_ifname = vms_info[target_vm][1]
        target_ip = vms_info[target_vm][2]
        refer_ip = vms_info[refer_vm][2]
        session = vms_info[mirror_vm][3]

        error_context.context("Create mirror port in ovs", test.log.info)
        create_mirror_port(mirror_ifname, target_ifname, direction, ovs_name)
        ping_cmd = "ping -c 10 %s" % host_ip
        status, output = session.cmd_status_output(ping_cmd, timeout=60)
        if status == 0:
            ifcfg = session.cmd_output_safe("ifconfig")
            test.log.debug("Guest network info: %s", ifcfg)
            test.log.debug("Ping results: %s", output)
            test.fail("All packets from %s to host should lost" % mirror_vm)

        error_context.context("Start tcpdump threads in %s" % mirror_vm, test.log.info)
        ifup_cmd = "ifconfig %s 0 up" % mirror_nic
        session.cmd(ifup_cmd, timeout=60)
        for vm, ip in [(target_vm, target_ip), (refer_vm, refer_ip)]:
            tcpdump_cmd = "tcpdump -l -n host %s and icmp >" % ip
            tcpdump_cmd += "/tmp/tcpdump-%s.txt &" % vm
            test.log.info("tcpdump command: %s", tcpdump_cmd)
            session.sendline(tcpdump_cmd)

        error_context.context(
            "Start ping threads in %s %s" % (target_vm, refer_vm), test.log.info
        )
        for vm in [target_vm, refer_vm]:
            ses = vms_info[vm][3]
            nic_name = vms_info[vm][4]
            ip = vms_info[vm][2]
            ifup_cmd = "ifconfig %s %s/%s up" % (nic_name, ip, net_mask)
            ses.cmd(ifup_cmd)
            time.sleep(0.5)
            test.log.info("Ping host from %s", vm)
            ses.cmd("ping %s -c 100" % host_ip, timeout=150)

        error_context.context("Check tcpdump results", test.log.info)
        session.cmd_output_safe("pkill tcpdump")
        process.system("ovs-vsctl clear bridge %s mirrors" % ovs_name)
        ifup_cmd = "ifconfig %s %s/%s up" % (mirror_nic, mirror_ip, net_mask)
        session.cmd(ifup_cmd, timeout=60)
        time.sleep(0.5)
        for vm in [target_vm, refer_vm]:
            src_file = "/tmp/tcpdump-%s.txt" % vm
            dst_file = os.path.join(test.resultsdir, "tcpdump-%s.txt" % vm)
            vms_info[mirror_vm][0].copy_files_from(src_file, dst_file)
            fd = open(dst_file, "r")
            content = fd.read().strip()
            fd.close()
            if vm == refer_vm and content:
                test.fail(
                    "should not packet from %s dumped in %s" % (refer_vm, mirror_vm)
                )
            elif not check_tcpdump(content, target_ip, host_ip, direction):
                test.fail("Unexpect packages from %s dumped in %s" % (vm, mirror_vm))
    finally:
        for vm in vms_info:
            vms_info[vm][0].destroy(gracefully=False)
        for f in glob.glob("/var/log/openvswith/*.log"):
            dst = os.path.join(test.resultsdir, os.path.basename(f))
            shutil.copy(f, dst)
        process.system(ovs_remove_cmd, ignore_status=False, shell=True)
