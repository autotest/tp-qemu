import re
import os
import glob
import shutil
import time
import logging
from autotest.client import os_dep
from autotest.client.shared import error, utils
from virttest import utils_net


@error.context_aware
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

    def make_mirror_cmd(
            mirror_port, target_port, direction="all", netdst="ovs0"):
        """
        Generate create ovs port mirror command.

        :parm mirror_port: port name in ovs in mirror status.
        :parm target_port: port name in ovs be mirroring.
        :parm direction: mirror direction, all, only input or output.
        :parm netdst: ovs port name.

        :return: string of ovs port mirror command.
        """
        cmd = ["ovs-vsctl set Bridge %s mirrors=@m " % netdst]
        fun = lambda x: "-- --id=@%s get Port %s " % (x, x)
        cmd += map(fun, [mirror_port, target_port])
        if direction == "input":
            cmd.append(
                "-- --id=@m create Mirror name=input_of_%s" %
                target_port)
            cmd.append("select-dst-port=@%s" % target_port)
        elif direction == "output":
            cmd.append(
                "-- --id=@m create Mirror name=output_of_%s" % target_port)
            cmd.append("select-src-port=@%s" % target_port)
        else:
            cmd.append(
                "-- --id=@m create Mirror name=mirror_%s" % target_port)
            cmd.append("select-src-port=@%s" % target_port)
            cmd.append("select-dst-port=@%s" % target_port)
        cmd.append("output-port=@%s" % mirror_port)
        return " ".join(cmd)

    def create_mirror_port(mirror_port, target_port, direction, netdst):
        """
        Execute ovs port mirror command and check port really in mirror status.

        :parm mirror_port: port name in ovs in mirror status.
        :parm target_port: port name in ovs be mirroring.
        :parm direction: mirror direction, all, only input or output.
        :parm netdst: ovs port name.
        """
        mirror_cmd = make_mirror_cmd(mirror_port, target_port, direction, netdst)
        uuid = utils.system_output(mirror_cmd)
        output = utils.system_output("ovs-vsctl list mirror")
        if uuid not in output:
            logging.debug("Create OVS Mirror CMD: %s " % mirror_cmd)
            logging.debug("Ovs Info: %s " % output)
            raise error.TestFail("Setup mirorr port failed")

    def checkTcpdump(output, target_ip, host_ip, direction):
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
                logging.debug("Unexpect packet in line %d: %s" % (idx, _))
                return False
        return True

    os_dep.command("ovs-vsctl")
    if params.get("netdst") not in utils.system_output("ovs-vsctl show"):
        raise error.TestError("This is a openvswitch only test")

    netdst = params.get("netdst", "ovs0")
    direction = params.get("direction", "all")
    mirror_vm = params.get("mirror_vm", "vm1")
    target_vm = params.get("target_vm", "vm2")
    refer_vm = params.get("refer_vm", "vm3")
    login_timeout = int(params.get("login_timeout", "600"))
    ip_version = params.get("ip_version", "ipv4")
    host_ip = utils_net.get_ip_address_by_interface(netdst)
    try:
        vms_info = {}
        for p_vm in params.get("vms").split():
            o_vm = env.get_vm(p_vm)
            o_vm.verify_alive()
            session = o_vm.wait_for_serial_login(timeout=login_timeout)
            ifname = o_vm.get_ifname()
            ip = o_vm.wait_for_get_address(0, timeout=login_timeout,
                                           ip_version=ip_version)
            vms_info[p_vm] = [o_vm, ifname, ip, session]

        mirror_ifname = vms_info[mirror_vm][1]
        target_ifname = vms_info[target_vm][1]
        target_ip = vms_info[target_vm][2]
        refer_ip = vms_info[refer_vm][2]
        session = vms_info[mirror_vm][3]

        error.context("Create mirror port in ovs", logging.info)
        create_mirror_port(mirror_ifname, target_ifname, direction, netdst)
        ping_cmd = "ping -c 10 %s" % host_ip
        status, output = session.cmd_status_output(ping_cmd, timeout=60)
        if status == 0:
            ifcfg = session.cmd_output_safe("ifconfig")
            logging.debug("Guest network info: %s" % ifcfg)
            logging.debug("Ping results: %s" % output)
            raise error.TestFail("All packets from %s to host should lost"
                                 % mirror_vm)

        error.context("Start tcpdump threads in %s" % mirror_vm, logging.info)
        session.cmd("ifconfig eth0 0 up", timeout=60)
        for vm, ip in [(target_vm, target_ip), (refer_vm, refer_ip)]:
            tcpdump_cmd = "tcpdump -l -n host %s and icmp >" % ip
            tcpdump_cmd += "/tmp/tcpdump-%s.txt &" % vm
            session.sendline(tcpdump_cmd)
            time.sleep(0.5)

        error.context("Start ping threads in %s %s" % (target_vm, refer_vm),
                      logging.info)
        for vm in [target_vm, refer_vm]:
            ses = vms_info[vm][3]
            ses.cmd("ping %s -c 100" % host_ip, timeout=150)

        error.context("Check tcpdump results", logging.info)
        session.cmd_output_safe("pkill tcpdump")
        utils.system("ovs-vsctl clear bridge %s mirrors" % netdst)
        session.cmd("service network restart", timeout=60)
        for vm in [target_vm, refer_vm]:
            src_file = "/tmp/tcpdump-%s.txt" % vm
            dst_file = os.path.join(test.resultsdir, "tcpdump-%s.txt" % vm)
            vms_info[mirror_vm][0].copy_files_from(src_file, dst_file)
            fd = open(dst_file, "r")
            content = fd.read().strip()
            fd.close()
            if vm == refer_vm and content:
                raise error.TestFail(
                    "should not packet from %s dumped in %s" %
                    (refer_vm, mirror_vm))
            elif not checkTcpdump(content, target_ip, host_ip, direction):
                raise error.TestFail(
                    "Unexpect packages from %s dumped in %s" % (vm, mirror_vm))
    finally:
        for f in glob.glob("/var/log/openvswith/*.log"):
            dst = os.path.join(test.resultsdir, os.path.basename(f))
            shutil.copy(f, dst)
