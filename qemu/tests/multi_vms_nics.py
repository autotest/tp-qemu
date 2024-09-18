import re

from avocado.utils import cpu, process
from virttest import (
    env_process,
    error_context,
    remote,
    utils_misc,
    utils_net,
    utils_test,
)
from virttest.staging import utils_memory


@error_context.context_aware
def run(test, params, env):
    """
    KVM multi test:
    1) Log into guests
    2) Check all the nics available or not
    3) Ping among guest nic and host
       3.1) Ping with different packet size
       3.2) Flood ping test
       3.3) Final ping test
    4) Transfer files among guest nics and host
       4.1) Create file by dd command in guest
       4.2) Transfer file between nics
       4.3) Compare original file and transferred file
    5) ping among different nics
       5.1) Ping with different packet size
       5.2) Flood ping test
       5.3) Final ping test
    6) Transfer files among different nics
       6.1) Create file by dd command in guest
       6.2) Transfer file between nics
       6.3) Compare original file and transferred file
    7) Repeat step 3 - 6 on every nic.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def ping(session, nic, dst_ip, strick_check, flood_minutes):
        d_packet_size = [
            1,
            4,
            48,
            512,
            1440,
            1500,
            1505,
            4054,
            4055,
            4096,
            4192,
            8878,
            9000,
            32767,
            65507,
        ]
        packet_size = params.get("packet_size", "").split() or d_packet_size
        for size in packet_size:
            error_context.context("Ping with packet size %s" % size, test.log.info)
            status, output = utils_test.ping(
                dst_ip, 10, interface=nic, packetsize=size, timeout=30, session=session
            )
            if strict_check:
                ratio = utils_test.get_loss_ratio(output)
                if ratio != 0:
                    test.fail("Loss ratio is %s for packet size" " %s" % (ratio, size))
            else:
                if status != 0:
                    test.fail("Ping returns non-zero value %s" % output)

        error_context.context("Flood ping test", test.log.info)
        utils_test.ping(
            dst_ip,
            None,
            interface=nic,
            flood=True,
            output_func=None,
            timeout=flood_minutes * 60,
            session=session,
        )
        error_context.context("Final ping test", test.log.info)
        counts = params.get("ping_counts", 100)
        status, output = utils_test.ping(
            dst_ip, counts, interface=nic, timeout=float(counts) * 1.5, session=session
        )
        if strick_check == "yes":
            ratio = utils_test.get_loss_ratio(output)
            if ratio != 0:
                test.fail("Packet loss ratio is %s after flood" % ratio)
        else:
            if status != 0:
                test.fail("Ping returns non-zero value %s" % output)

    def file_transfer(session, src, dst):
        username = params.get("username", "")
        password = params.get("password", "")
        src_path = "/tmp/1"
        dst_path = "/tmp/2"
        port = int(params["file_transfer_port"])

        cmd = "dd if=/dev/urandom of=%s bs=100M count=1" % src_path
        cmd = params.get("file_create_cmd", cmd)

        error_context.context("Create file by dd command, cmd: %s" % cmd, test.log.info)
        session.cmd(cmd)

        transfer_timeout = int(params.get("transfer_timeout"))
        log_filename = "scp-from-%s-to-%s.log" % (src, dst)
        error_context.context("Transfer file from %s to %s" % (src, dst), test.log.info)
        remote.scp_between_remotes(
            src,
            dst,
            port,
            password,
            password,
            username,
            username,
            src_path,
            dst_path,
            log_filename=log_filename,
            timeout=transfer_timeout,
        )
        src_path = dst_path
        dst_path = "/tmp/3"
        log_filename = "scp-from-%s-to-%s.log" % (dst, src)
        error_context.context("Transfer file from %s to %s" % (dst, src), test.log.info)
        remote.scp_between_remotes(
            dst,
            src,
            port,
            password,
            password,
            username,
            username,
            src_path,
            dst_path,
            log_filename=log_filename,
            timeout=transfer_timeout,
        )
        error_context.context(
            "Compare original file and transferred file", test.log.info
        )

        cmd1 = "md5sum /tmp/1"
        cmd2 = "md5sum /tmp/3"
        md5sum1 = session.cmd(cmd1).split()[0]
        md5sum2 = session.cmd(cmd2).split()[0]
        if md5sum1 != md5sum2:
            test.error("File changed after transfer")

    nic_interface_list = []
    check_irqbalance_cmd = params.get(
        "check_irqbalance_cmd", "systemctl status irqbalance"
    )
    stop_irqbalance_cmd = params.get("stop_irqbalance_cmd", "systemctl stop irqbalance")
    start_irqbalance_cmd = params.get(
        "start_irqbalance_cmd", "systemctl start irqbalance"
    )
    status_irqbalance = params.get("status_irqbalance", "Active: active|running")
    vms = params["vms"].split()
    host_mem = utils_memory.memtotal() // (1024 * 1024)
    host_cpu_count = cpu.total_count()
    vhost_count = 0
    if params.get("vhost"):
        vhost_count = 1
    if host_cpu_count < (1 + vhost_count) * len(vms):
        test.error(
            "The host don't have enough cpus to start guest"
            "pcus: %d, minimum of vcpus and vhost: %d"
            % (host_cpu_count, (1 + vhost_count) * len(vms))
        )
    params["mem"] = host_mem // len(vms) * 1024
    params["smp"] = params["vcpu_maxcpus"] = host_cpu_count // len(vms) - vhost_count
    if params["smp"] % 2 != 0:
        params["vcpu_sockets"] = 1
    params["start_vm"] = "yes"
    for vm_name in vms:
        env_process.preprocess_vm(test, params, env, vm_name)
    timeout = float(params.get("login_timeout", 360))
    strict_check = params.get("strick_check", "no")
    host_ip = utils_net.get_ip_address_by_interface(params.get("netdst"))
    host_ip = params.get("srchost", host_ip)
    flood_minutes = float(params["flood_minutes"])
    error_context.context("Check irqbalance service status", test.log.info)
    o = process.system_output(
        check_irqbalance_cmd, ignore_status=True, shell=True
    ).decode()
    check_stop_irqbalance = False
    if re.findall(status_irqbalance, o):
        test.log.debug("stop irqbalance")
        process.run(stop_irqbalance_cmd, shell=True)
        check_stop_irqbalance = True
        o = process.system_output(
            check_irqbalance_cmd, ignore_status=True, shell=True
        ).decode()
        if re.findall(status_irqbalance, o):
            test.error("Can not stop irqbalance")
    thread_list = []
    nic_interface = []
    for vm_name in vms:
        guest_ifname = ""
        guest_ip = ""
        vm = env.get_vm(vm_name)
        session = vm.wait_for_login(timeout=timeout)
        thread_list.extend(vm.vcpu_threads)
        thread_list.extend(vm.vhost_threads)
        error_context.context("Check all the nics available or not", test.log.info)
        for index, nic in enumerate(vm.virtnet):
            guest_ifname = utils_net.get_linux_ifname(session, nic.mac)
            guest_ip = vm.get_address(index)
            if not (guest_ifname and guest_ip):
                err_log = "vms %s get ip or ifname failed." % vm_name
                err_log = "ifname: %s, ip: %s." % (guest_ifname, guest_ip)
                test.fail(err_log)
            nic_interface = [guest_ifname, guest_ip, session]
            nic_interface_list.append(nic_interface)
    error_context.context("Pin vcpus and vhosts to host cpus", test.log.info)
    host_numa_nodes = utils_misc.NumaInfo()
    vthread_num = 0
    for numa_node_id in host_numa_nodes.nodes:
        numa_node = host_numa_nodes.nodes[numa_node_id]
        for _ in range(len(numa_node.cpus)):
            if vthread_num >= len(thread_list):
                break
            vcpu_tid = thread_list[vthread_num]
            test.log.debug(
                "pin vcpu/vhost thread(%s) to cpu(%s)",
                vcpu_tid,
                numa_node.pin_cpu(vcpu_tid),
            )
            vthread_num += 1

    nic_interface_list_len = len(nic_interface_list)
    # ping and file transfer test
    for src_ip_index in range(nic_interface_list_len):
        error_context.context("Ping test from guest to host", test.log.info)
        src_ip_info = nic_interface_list[src_ip_index]
        ping(src_ip_info[2], src_ip_info[0], host_ip, strict_check, flood_minutes)
        error_context.context(
            "File transfer test between guest and host", test.log.info
        )
        file_transfer(src_ip_info[2], src_ip_info[1], host_ip)
        for dst_ip in nic_interface_list[src_ip_index:]:
            if src_ip_info[1] == dst_ip[1]:
                continue
            txt = "Ping test between %s and %s" % (src_ip_info[1], dst_ip[1])
            error_context.context(txt, test.log.info)
            ping(src_ip_info[2], src_ip_info[0], dst_ip[1], strict_check, flood_minutes)
            txt = "File transfer test between %s " % src_ip_info[1]
            txt += "and %s" % dst_ip[1]
            error_context.context(txt, test.log.info)
            file_transfer(src_ip_info[2], src_ip_info[1], dst_ip[1])
    if check_stop_irqbalance:
        process.run(start_irqbalance_cmd, shell=True)
