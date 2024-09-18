import time

from avocado.utils import linux_modules, process
from virttest import error_context, funcatexit, utils_net, utils_test


class NetPingError(utils_net.NetError):
    def __init__(self, src, dst, details):
        utils_net.NetError.__init__(self, src, details)
        self.dst = dst

    def __str__(self):
        e_msg = "Can't ping from %s to %s" % (self.src, self.dst)
        if self.details is not None:
            e_msg += " : %s" % self.details
        return e_msg


def _system(*args, **kwargs):
    kwargs["shell"] = True
    return process.system(*args, **kwargs)


@error_context.context_aware
def run(test, params, env):
    """
    Test 802.1Q vlan of NIC among guests and host with linux bridge backend.

    1) Configure vlan interface over host bridge interface.
    2) Create two VMs over vlan interface.
    3) Load 8021q module in guest.
    4) Configure ip address of guest with 192.168.*.*
    5) Test by ping between guest and host, should fail.
    6) Test by ping beween guests, should pass.
    7) Setup vlan in guests and using hard-coded ip address 192.168.*.*
    8) Test by ping between guest and host, should pass.
    9) Test by ping among guests, should pass.
    10) Test by netperf between guests and host.
    11) Test by netperf between guests.
    12) Delete vlan interface in host.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def add_vlan(interface, v_id, session=None):
        """
        Create a vlan-device on interface.
        :params interface: Interface.
        :params v_id: Vlan id.
        :params session: VM session or none.
        """
        vlan_if = "%s.%s" % (interface, v_id)
        add_cmd = params["add_vlan_cmd"] % (interface, vlan_if, v_id)
        error_context.context(
            "Create vlan interface '%s' on %s" % (vlan_if, interface), test.log.info
        )
        if session:
            session.cmd_output_safe(add_cmd)
        else:
            process.system(add_cmd)
        return vlan_if

    def set_ip_vlan(vlan_if, vlan_ip, session=None):
        """
        Set ip address of vlan interface.
        :params vlan_if: Vlan interface.
        :params vlan_ip: Vlan internal ip.
        :params session: VM session or none.
        """
        error_context.context(
            "Assign IP '%s' to vlan interface '%s'" % (vlan_ip, vlan_if), test.log.info
        )
        if session:
            disable_firewall = params.get("disable_firewall", "")
            session.cmd_output_safe(disable_firewall)
            disable_nm = params.get("disable_nm", "")
            session.cmd_output_safe(disable_nm)
            session.cmd_output_safe("ifconfig %s 0.0.0.0" % vlan_if)
            session.cmd_output_safe("ifconfig %s down" % vlan_if)
            session.cmd_output_safe("ifconfig %s %s up" % (vlan_if, vlan_ip))
        else:
            process.system("ifconfig %s %s up" % (vlan_if, vlan_ip))

    def set_mac_vlan(vlan_if, mac_str, session):
        """
        Give a new mac address for vlan interface in guest.
        :params: vlan_if: Vlan interface.
        :params: mac_str: New mac address for vlan.
        :params: session: VM session.
        """
        mac_cmd = "ip link set %s add %s up" % (vlan_if, mac_str)
        error_context.context(
            "Give a new mac address '%s' for vlan interface "
            "'%s'" % (mac_str, vlan_if),
            test.log.info,
        )
        session.cmd_output_safe(mac_cmd)

    def set_arp_ignore(session):
        """
        Enable arp_ignore for all ipv4 device in guest
        """
        error_context.context(
            "Enable arp_ignore for all ipv4 device in guest", test.log.info
        )
        ignore_cmd = "echo 1 > /proc/sys/net/ipv4/conf/all/arp_ignore"
        session.cmd_output_safe(ignore_cmd)

    def ping_vlan(vm, dest, vlan_if, session):
        """
        Test ping between vlans, from guest to host/guest.
        :params vm: VM object
        :params dest: Dest ip to ping.
        :params vlan_if: Vlan interface.
        :params session: VM session.
        """
        error_context.context(
            "Test ping from '%s' to '%s' on guest '%s'" % (vlan_if, dest, vm.name)
        )
        status, output = utils_test.ping(
            dest=dest, count=10, interface=vlan_if, session=session, timeout=30
        )
        if status:
            raise NetPingError(vlan_if, dest, output)

    def netperf_vlan(client="main_vm", server="localhost", sub_type="netperf_stress"):
        """
        Test netperf stress among guests and host.
        :params client: Netperf client.
        :params server: Netperf server.
        :params sub_type: Sub_type to run.
        """
        params["netperf_client"] = client
        params["netperf_server"] = server
        error_context.context(
            "Run netperf stress test among guests and host, "
            "server: %s, client: %s" % (server, client),
            test.log.info,
        )
        session.cmd_output_safe("systemctl restart NetworkManager")
        utils_test.run_virt_sub_test(test, params, env, sub_type)

    vms = []
    sessions = []
    ifname = []
    vm_ip = []
    vm_vlan_ip = []
    vm_vlan_if = []
    sub_type = params["sub_type"]
    host_br = params.get("netdst", "switch")
    host_vlan_id = params.get("host_vlan_id", "10")
    host_vlan_ip = params.get("host_vlan_ip", "192.168.10.10")
    subnet = params.get("subnet", "192.168")
    mac_str = params.get("mac_str").split(",")

    br_backend = utils_net.find_bridge_manager(host_br)
    if not isinstance(br_backend, utils_net.Bridge):
        test.cancel("Host does not use Linux Bridge")

    linux_modules.load_module("8021q")

    host_vlan_if = "%s.%s" % (host_br, host_vlan_id)
    if host_vlan_if not in utils_net.get_net_if():
        host_vlan_if = add_vlan(interface=host_br, v_id=host_vlan_id)
        if host_vlan_if in utils_net.get_net_if():
            set_ip_vlan(vlan_if=host_vlan_if, vlan_ip=host_vlan_ip)
            rm_host_vlan_cmd = params["rm_host_vlan_cmd"] % host_vlan_if
            funcatexit.register(env, params["type"], _system, rm_host_vlan_cmd)
        else:
            test.cancel("Fail to set up vlan over bridge interface in host!")

    if params.get("start_vm", "yes") == "no":
        vm_main = env.get_vm(params["main_vm"])
        vm_main.create(params=params)
        vm2 = env.get_vm("vm2")
        vm2.create(params=params)
        vms.append(vm_main)
        vms.append(vm2)
    else:
        vms.append(env.get_vm([params["main_vm"]]))
        vms.append(env.get_vm("vm2"))

    for vm_ in vms:
        vm_.verify_alive()

    for vm_index, vm in enumerate(vms):
        error_context.context("Prepare test env on %s" % vm.name)
        session = vm.wait_for_serial_login()
        if not session:
            err_msg = "Could not log into guest %s" % vm.name
            test.error(err_msg)

        interface = utils_net.get_linux_ifname(session, vm.get_mac_address())

        error_context.context("Load 8021q module in guest %s" % vm.name, test.log.info)
        session.cmd_output_safe("modprobe 8021q")

        error_context.context(
            "Setup vlan environment in guest %s" % vm.name, test.log.info
        )
        inter_ip = "%s.%s.%d" % (subnet, host_vlan_id, vm_index + 1)
        set_ip_vlan(interface, inter_ip, session=session)
        set_arp_ignore(session)
        params["vlan_nic"] = "%s.%s" % (interface, host_vlan_id)
        error_context.context(
            "Test ping from guest '%s' to host with "
            "interface '%s'" % (vm.name, interface),
            test.log.info,
        )
        try:
            ping_vlan(vm, dest=host_vlan_ip, vlan_if=interface, session=session)
        except NetPingError:
            test.log.info(
                "Guest ping fail to host as expected with " "interface '%s'", interface
            )
        else:
            test.fail(
                "Guest ping to host should fail with interface" " '%s'" % interface
            )
        ifname.append(interface)
        vm_ip.append(inter_ip)
        sessions.append(session)

    # Ping succeed between guests
    error_context.context(
        "Test ping between guests with interface %s" % ifname[0], test.log.info
    )
    ping_vlan(vms[0], dest=vm_ip[1], vlan_if=ifname[0], session=sessions[0])

    # set vlan tag for guest
    for vm_index, vm in enumerate(vms):
        session = sessions[vm_index]
        error_context.context("Add vlan interface on guest '%s'" % vm.name)
        session.cmd_output("ifconfig %s 0.0.0.0" % ifname[vm_index], safe=True)
        vlan_if = add_vlan(
            interface=ifname[vm_index], v_id=host_vlan_id, session=session
        )
        vm_vlan_if.append(vlan_if)
        set_mac_vlan(vlan_if, mac_str[vm_index], session=session)
        vlan_ip = "%s.%s.%d" % (subnet, host_vlan_id, vm_index + 11)
        set_ip_vlan(vlan_if, vlan_ip, session=session)
        vm_vlan_ip.append(vlan_ip)

        error_context.context(
            "Test ping from interface '%s' on guest "
            "'%s' to host." % (vm_vlan_if[vm_index], vm.name),
            test.log.info,
        )
        utils_net.restart_guest_network(session)
        ping_vlan(vm, dest=host_vlan_ip, vlan_if=vm_vlan_if[vm_index], session=session)
        netperf_vlan(client=vm.name, server="localhost")

    error_context.context(
        "Test ping and netperf between guests with "
        "interface '%s'" % vm_vlan_if[vm_index],
        test.log.info,
    )
    ping_vlan(vms[0], dest=vm_vlan_ip[1], vlan_if=vm_vlan_if[0], session=sessions[0])
    netperf_vlan(client=params["main_vm"], server="vm2")

    exithandlers = "exithandlers__%s" % sub_type
    sub_exit_timeout = int(params.get("sub_exit_timeout", 10))
    start_time = time.time()
    end_time = start_time + float(sub_exit_timeout)

    while time.time() < end_time:
        test.log.debug(
            "%s (%f secs)", sub_type + " is running", (time.time() - start_time)
        )
        if env.data.get(exithandlers):
            break
        time.sleep(1)

    for sess in sessions:
        if sess:
            sess.close()
