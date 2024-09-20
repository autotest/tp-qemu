import logging
import os.path

from avocado.utils import process
from virttest import data_dir, env_process, error_context, remote, utils_net, utils_test

LOG_JOB = logging.getLogger("avocado.test")


def create_file_in_guest(
    test, session, file_path, size=100, os_type="linux", timeout=360
):
    """
    Create a file with 'dd' in guest.

    :param test: QEMU test object
    :param session: in which guest to do the file creation
    :param file_path: put the created file in which directory
    :param size: file size
    :param os_type: linux or windows
    :param timeout: file creation command timeout
    """
    size = int(size)
    if os_type == "linux":
        cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (file_path, size)
    else:
        cmd = "fsutil file createnew %s %s" % (file_path, size * 1024 * 1024)
    status, output = session.cmd_status_output(cmd, timeout=timeout)
    if status:
        err = "Fail to create file in guest."
        err += " command '%s', output '%s'." % (cmd, output)
        test.error(err)


def ping_result_check(test, loss_ratio, same_vlan):
    """
    Ping result check.

    :param test: QEMU test object
    :param loss_ratio: ping test loss ratio
    :param same_vlan: whether the two guests are in the same vlan
    """
    if same_vlan and loss_ratio > 0:
        msg = "Package lost when ping guest in same vlan."
        msg += "Loss ratio is %s" % loss_ratio
        test.fail(msg)
    if not same_vlan and loss_ratio != 100:
        msg = "Ping between guest in different vlan successful."
        msg += "Loss ratio is %s" % loss_ratio
        test.fail(msg)


def ping(test, os_type, match_error, dest, count, session, same_vlan):
    """
    In 'session' ping 'dest'.
    If the two guests are in the same vlan, loss ratio should be 0%.
    Otherwise, loss ratio should be 100%.

    :param test: QEMU test object
    :param dest: dest ip address
    :param count: ping count
    :param session: in which guest to do ping test
    :param same_vlan: whether the two guests are in the same vlan
    """
    if os_type == "linux":
        status, output = utils_test.ping(dest, count, timeout=60, session=session)
        loss_ratio = utils_test.get_loss_ratio(output)
        ping_result_check(test, loss_ratio, same_vlan)
        LOG_JOB.debug(output)
    elif os_type == "windows":  # TODO, not supported by now
        status, output = utils_test.ping(dest, count, timeout=60, session=session)
        if match_error in str(output):
            pass
        else:
            loss_ratio = utils_test.get_loss_ratio(output)
        ping_result_check(test, loss_ratio, same_vlan)


def netperf_setup(test, params, env):
    """
    Setup netperf in guest.

    Copy netperf package into guest. Install netperf in guest (linux only).
    """
    params["start_vm"] = "yes"
    params["image_snapshot"] = "no"
    vm_name = params.get("main_vm")
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    try:
        if params.get("os_type") == "linux":
            netperf_link = params["netperf_link"]
            netperf_path = params["netperf_path"]
            src_link = os.path.join(data_dir.get_deps_dir("netperf"), netperf_link)
            vm.copy_files_to(src_link, netperf_path, timeout=60)
            setup_cmd = params.get("setup_cmd")
            (status, output) = session.cmd_status_output(
                setup_cmd % netperf_path, timeout=600
            )
            if status != 0:
                err = "Fail to setup netperf on guest os."
                err += " Command output:\n%s" % output
                test.error(err)
        elif params.get("os_type") == "windows":
            # TODO, not suppoted by now
            s_link = params.get("netperf_server_link_win", "netserver-2.6.0.exe")
            src_link = os.path.join(data_dir.get_deps_dir("netperf"), s_link)
            netperf_path = params["netperf_path"]
            vm.copy_files_to(src_link, netperf_path, timeout=60)
            s_link = params.get("netperf_client_link_win", "netperf.exe")
            src_link = os.path.join(data_dir.get_deps_dir("netperf"), s_link)
            vm.copy_files_to(src_link, netperf_path, timeout=60)
    finally:
        if session:
            session.close()
        vm.destroy()


@error_context.context_aware
def run(test, params, env):
    """
    QEMU 'open vswitch host vlan' test

    1) Start a VM and setup netperf in it
    2) Stop NetworkManager service in host
    3) Create a new private ovs bridge, which has no physical nics inside
    4) Create 4 ovs ports and add to 2 vlans
    4) Boot 4 VMs on this bridge and add them to 2 vlans
    5) Configure ip address of all systems make sure all IPs are in same
       subnet
    6) Ping between two guests in same vlan
    7) Ping between two guests in different vlan
    8) Ping between two guests in another vlan
    9) Netperf test between two guests in same vlan
    10) Transfer file between two guests in same vlan (optional)

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    txt = "Setup netperf in guest."
    image_snapshot = params.get("image_snapshot", "yes")
    error_context.context(txt, test.log.info)
    netperf_setup(test, params, env)
    params["image_snapshot"] = image_snapshot

    os_type = params.get("os_type", "linux")
    bridge_name = params.get("private_vlan_bridge", "ovs_private_br")
    login_timeout = int(params.get("login_timeout", 360))
    match_error = params.get("destination_unreachable", "")

    txt = "Stop NetworkManager service in host."
    error_context.context(txt, test.log.info)
    process.system(params["stop_network_manager"], timeout=120, ignore_status=True)

    txt = "Create a new private ovs bridge, which has"
    txt += " no physical nics inside."
    error_context.context(txt, test.log.info)
    ovs_br_create_cmd = params["ovs_br_create_cmd"]
    ovs_br_remove_cmd = params["ovs_br_remove_cmd"]
    try:
        process.system(ovs_br_create_cmd, shell=True)
    except process.CmdError:
        test.fail("Fail to create ovs bridge %s" % bridge_name)

    sessions = []
    try:
        params["start_vm"] = "yes"
        params["netdst"] = bridge_name
        vms = params.get("vms").split()
        ips = []
        txt = "Start multi vms and add them to 2 vlans."
        error_context.context(txt, test.log.info)
        for vm_name in vms:
            vm_params = params.object_params(vm_name)
            env_process.preprocess_vm(test, vm_params, env, vm_name)
            vm = env.get_vm(vm_name)
            ifname = vm.virtnet[0]["ifname"]
            guest_ip = vm.virtnet[0].ip
            vlan = vm_params["ovs_port_vlan"]
            create_port_cmd = "ovs-vsctl set Port %s tag=%s" % (ifname, vlan)
            try:
                output = process.system_output(
                    create_port_cmd, timeout=120, ignore_status=False
                ).decode()
                process.system_output("ovs-vsctl show")
            except process.CmdError:
                err = "Fail to create ovs port %s " % ifname
                err += "on bridge %s." % bridge_name
                err += " Command: %s, " % create_port_cmd
                err += "output: %s." % output
                test.fail(err)

            session_ctl = vm.wait_for_serial_login(timeout=login_timeout)
            if os_type == "linux":
                txt = "Stop NetworkManager service in guest %s." % vm_name
                test.log.info(txt)
                session_ctl.cmd(params["stop_network_manager"], timeout=120)

            mac = vm.get_mac_address()
            txt = "Set guest %s mac %s IP to %s" % (vm_name, mac, guest_ip)
            error_context.context(txt, test.log.info)
            utils_net.set_guest_ip_addr(session_ctl, mac, guest_ip, os_type=os_type)
            utils_net.Interface(ifname).down()
            utils_net.Interface(ifname).up()
            ips.append(guest_ip)
            sessions.append(session_ctl)

        txt = "Ping between two guests in same vlan. %s -> %s" % (vms[0], vms[1])
        error_context.context(txt, test.log.info)
        ping(
            test,
            os_type,
            match_error,
            ips[1],
            count=10,
            session=sessions[0],
            same_vlan=True,
        )

        txt = "Ping between two guests in different "
        txt += "vlan. %s -> %s" % (vms[0], vms[2])
        error_context.context(txt, test.log.info)
        ping(
            test,
            os_type,
            match_error,
            ips[2],
            count=10,
            session=sessions[0],
            same_vlan=False,
        )

        txt = "Ping between two guests in another "
        txt += "vlan. %s -> %s" % (vms[2], vms[3])
        error_context.context(txt, test.log.info)
        ping(
            test,
            os_type,
            match_error,
            ips[3],
            count=10,
            session=sessions[2],
            same_vlan=True,
        )

        txt = "Netperf test between two guests in same vlan."
        txt += "%s -> %s" % (vms[0], vms[1])
        error_context.context(txt, test.log.info)

        txt = "Run netserver in VM %s" % vms[0]
        error_context.context(txt, test.log.info)
        shutdown_firewall_cmd = params["shutdown_firewall"]
        sessions[0].cmd_status_output(shutdown_firewall_cmd, timeout=10)
        netserver_cmd = params.get("netserver_cmd")
        netperf_path = params.get("netperf_path")
        cmd = os.path.join(netperf_path, netserver_cmd)
        status, output = sessions[0].cmd_status_output(cmd, timeout=60)
        if status != 0:
            err = "Fail to start netserver in VM."
            err += " Command output %s" % output
            test.error(err)

        txt = "Run netperf client in VM %s" % vms[1]
        error_context.context(txt, test.log.info)
        sessions[1].cmd_status_output(shutdown_firewall_cmd, timeout=10)
        test_duration = int(params.get("netperf_test_duration", 60))
        test_protocol = params.get("test_protocol")
        netperf_cmd = params.get("netperf_cmd")
        netperf_cmd = os.path.join(netperf_path, netperf_cmd)
        cmd = netperf_cmd % (test_duration, ips[0])
        if test_protocol:
            cmd += " -t %s" % test_protocol
        cmd_timeout = test_duration + 20
        status, output = sessions[1].cmd_status_output(cmd, timeout=cmd_timeout)
        if status != 0:
            err = "Fail to run netperf test between %s and %s." % (vms[0], vms[1])
            err += " Command output:\n%s" % output
            test.fail(err)

        if params.get("file_transfer_test", "yes") == "yes":
            filesize = int(params.get("filesize", 1024))
            file_create_timeout = int(params.get("file_create_timeout", 720))
            file_path = params.get("file_path", "/var/tmp/src_file")

            txt = "Create %s MB file %s in %s" % (filesize, file_path, vms[0])
            error_context.context(txt, test.log.info)
            create_file_in_guest(
                test,
                session=sessions[0],
                file_path=file_path,
                size=filesize,
                os_type=os_type,
                timeout=file_create_timeout,
            )

            txt = "Transfer file %s between guests in same " % file_path
            txt += "vlan. %s -> %s" % (vms[0], vms[1])
            error_context.context(txt, test.log.info)
            password = params.get("password", "kvmautotest")
            username = params.get("username", "root")
            f_tmout = int(params.get("file_transfer_timeout", 1200))
            shell_port = params.get("shell_port", "22")
            data_port = params.get("nc_file_transfer_port", "9000")
            "file_transfer_from_%s_to_%s.log" % (ips[0], ips[1])
            if os_type == "linux":  # TODO, windows will be supported later
                remote.nc_copy_between_remotes(
                    ips[0],
                    ips[1],
                    shell_port,
                    password,
                    password,
                    username,
                    username,
                    file_path,
                    file_path,
                    d_port=data_port,
                    timeout=2,
                    check_sum=True,
                    s_session=sessions[0],
                    d_session=sessions[1],
                    file_transfer_timeout=f_tmout,
                )
    finally:
        for session in sessions:
            if session:
                session.close()
        process.system(ovs_br_remove_cmd, ignore_status=False, shell=True)
