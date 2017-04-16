import logging
import time
import os.path
from autotest.client import utils
from autotest.client.shared import error
from virttest import remote
from virttest import data_dir
from virttest import utils_net
from virttest import utils_test
from virttest import env_process


def create_file_in_guest(session, file_path, size=100, os_type="linux", timeout=360):
    size = int(size)
    if os_type == "linux":
        cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (file_path, size)
    else:
        cmd = "fsutil file createnew %s %s" % (file_path, size * 1024 * 1024)
    status, output = session.cmd_status_output(cmd, timeout=timeout)
    if status:
        err = "Fail to create file in guest."
        err += " command '%s', output '%s'." % (cmd, output)
        raise error.TestError(err)


def ping(dest, count, session, same_vlan=True, os_type="linux"):
    _, output = utils_test.ping(dest, count, timeout=int(count) * 1.5,
                                session=session, os_type=os_type)
    ratio = utils_test.get_loss_ratio(output)
    if same_vlan and ratio > 0:
        msg = "Package lost when ping guest in same vlan."
        msg += "Loss ratio is %s" % ratio
        raise error.TestFail(msg)
    if not same_vlan and ratio != 100:
        msg = "Ping between guest in different vlan successful."
        msg += "Loss ratio is %s" % ratio
        raise error.TestFail(msg)


def netperf_setup(test, params, env):
    """
    Setup netperf in guest.

    Copy netperf package into guest. Install netperf in guest (linux only).
    """
    tmp_params = params
    tmp_params["start_vm"] = "yes"
    tmp_params["image_snapshot"] = "no"
    vm_name = params.get("main_vm")
    env_process.preprocess_vm(test, tmp_params, env, vm_name)
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
            (status, output) = session.cmd_status_output(setup_cmd % netperf_path,
                                                         timeout=600)
            if status != 0:
                err = "Fail to setup netperf on guest os."
                err += " Command output:\n%s" % output
                raise error.TestError(err)
        elif params.get("os_type") == "Windows":
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


@error.context_aware
def run(test, params, env):
    """
    QEMU 'open vswitch host vlan' test

    1) Start a VM and setup netperf in it.
    2) Stop NetworkManager service in host.
    3) Create a new private ovs bridge, which has no physical nics inside.
    4) Create 4 ovs ports and add to 2 vlans.
    4) Boot 4 VMs on this bridge and add them to 2 vlans.
    5) Configure ip address of all systems make sure all IPs are in same subnet.
    6) Ping between two guests in same vlan.
    7) Ping between two guests in different vlan.
    8) Ping between two guests in another vlan.
    9) Netperf test between two guests in same vlan.
    10) Transfer file between to guests in same vlan. (optional)

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    txt = "Setup netperf in guest."
    image_snapshot = params.get("image_snapshot")
    error.context(txt, logging.info)
    netperf_setup(test, params, env)
    params["image_snapshot"] = image_snapshot

    os_type = params.get("os_type", "linux")
    bridge_name = params.get("private_vlan_bridge", "ovs_private_br")
    login_timeout = int(params.get("login_timeout", 360))

    txt = "Stop NetworkManager service in host."
    error.context(txt, logging.info)
    cmd = "service NetworkManager stop"
    utils.system(cmd, timeout=120, ignore_status=True)

    txt = "Create a new private ovs bridge, which has"
    txt += " no physical nics inside."
    error.context(txt, logging.info)
    create_ovs_cmd = "ovs-vsctl add-br %s" % bridge_name
    try:
        utils.system(create_ovs_cmd, timeout=120, ignore_status=False)
    except error.CmdError:
        raise error.TestFail("Fail to create ovs bridge %s" % bridge_name)

    try:
        params["start_vm"] = "yes"
        params["netdst"] = bridge_name
        vms = params.get("vms").split()
        sessions = []
        ips = []
        txt = "Start multi vms and add them to 2 vlans."
        error.context(txt, logging.info)
        for vm_name in vms:
            vm_params = params.object_params(vm_name)
            env_process.preprocess_vm(test, vm_params, env, vm_name)
        for vm_name in vms:
            vm_params = params.object_params(vm_name)
            change_ip_cmd = vm_params.get("change_ip_cmd", "ifconfig %s %s")
            vm = env.get_vm(vm_name)
            ifname = vm.virtnet[0]["ifname"]
            guest_ip = vm.virtnet[0].ip
            vlan = vm_params.get("ovs_port_vlan")
            create_port_cmd = "ovs-vsctl set Port %s tag=%s" % (ifname, vlan)
            try:
                output = ""
                output = utils.system_output(create_port_cmd, timeout=120,
                                             ignore_status=False)
            except error.CmdError:
                err = "Fail to create ovs port %s on bridge %s." % (ifname,
                                                                    bridge_name)
                err += " Command: %s, output: %s." % (create_port_cmd, output)
                raise error.TestFail(err)

            session_ctl = vm.wait_for_serial_login(timeout=login_timeout)
            txt = "Stop NetworkManager service in guest %s." % vm_name
            session_ctl.cmd("service NetworkManager stop",
                            ignore_all_errors=True)

            txt = "Set guest %s IP to %s" % (vm_name, guest_ip)
            error.context(txt, logging.info)
            mac = vm.get_mac_address()
            utils_net.set_guest_ip_addr(session_ctl, mac, guest_ip,
                                        os_type=os_type)
            ips.append(guest_ip)
            sessions.append(session_ctl)

        txt = "Ping between two guests in same vlan. %s -> %s" % (vms[0],
                                                                  vms[1])
        error.context(txt, logging.info)
        ping(ips[1], count=100, session=sessions[0], same_vlan=True,
             os_type=os_type)

        txt = "Ping between two guests in different vlan. %s -> %s" % (vms[0],
                                                                       vms[2])
        error.context(txt, logging.info)
        ping(ips[2], count=100, session=sessions[0], same_vlan=False)

        txt = "Ping between two guests in another vlan. %s -> %s" % (vms[2],
                                                                     vms[3])
        error.context(txt, logging.info)
        ping(ips[2], count=100, session=sessions[3], same_vlan=True)

        txt = "Netperf test between two guests in same vlan."
        txt += "%s -> %s" % (vms[0], vms[1])
        error.context(txt, logging.info)

        txt = "Run netserver in VM %s" % vms[0]
        error.context(txt, logging.info)
        netserver_cmd = params.get("netserver_cmd")
        netperf_path = params.get("netperf_path")
        cmd = os.path.join(netperf_path, netserver_cmd)
        status, output = sessions[0].cmd_status_output(cmd, timeout=60)
        if status != 0:
            err = "Fail to start netserver in VM."
            err += " Command output %s" % output
            raise error.TestError(err)

        txt = "Run netperf client in VM %s" % vms[1]
        error.context(txt, logging.info)
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
            err = "Fail to run netperf test between %s and %s." % (vms[0],
                                                                   vms[1])
            err += " Command output:\n%s" % output
            raise error.TestFail(err)

        if params.get("file_transfer_test", "yes") == "yes":
            filesize = int(params.get("filesize", 1024))
            file_create_timeout = int(params.get("file_create_timeout", 720))
            file_path = params.get("file_path", "/var/tmp/src_file")

            txt = "Create %s MB file %s in %s" % (filesize, file_path, vms[0])
            error.context(txt, logging.info)
            create_file_in_guest(session=sessions[0], file_path=file_path,
                                 size=filesize, os_type=os_type,
                                 timeout=file_create_timeout)

            txt = "Transfer file %s between guests in same vlan. " % file_path
            txt += "%s -> %s" % (vms[0], vms[1])
            error.context(txt, logging.info)
            password = params.get("password", "redhat")
            username = params.get("username", "root")
            f_timeout = int(params.get("file_transfer_timeout", 1200))
            shell_port = params.get("shell_port", "22")
            data_port = params.get("nc_file_transfer_port", "9000")
            log_file = "file_transfer_from_%s_to_%s.log" % (ips[0], ips[1])
            if os_type == "linux":
                remote.nc_copy_between_remotes(ips[0], ips[1], shell_port,
                                               password, password,
                                               username, username,
                                               file_path, file_path,
                                               d_port=data_port,
                                               timeout=2,
                                               check_sum=True,
                                               s_session=sessions[0],
                                               d_session=sessions[1],
                                               file_transfer_timeout=f_timeout)
    finally:
        ovs_del_cmd = "ovs-vsctl del-br %s" % bridge_name
        utils.system(ovs_del_cmd, timeout=120, ignore_status=True)
