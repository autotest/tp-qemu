import logging

from avocado.utils import process
from virttest import openvswitch, utils_net

LOG_JOB = logging.getLogger("avocado.test")


def check_ovs_status():
    """
    Check if ovs-vsctl and openvswitch service are installed and running.
    :return:  True if both are available and running, otherwise False
    :rtype: bool
    """
    cmd = "which ovs-vsctl && systemctl status openvswitch.service"
    return process.system(cmd, ignore_status=True, shell=True) == 0


def get_vf_pci_address(nic_netdst):
    """
    Get vf pci address from a given network destination.

    :param nic_netdst: Network destination address
    :type nic_netdst: str

    :return: VF pci address
    :rtype: str
    """
    cmd = (
        "vdpa dev show | grep {0} | grep -o 'pci/[^[:space:]]*' | "
        "awk -F/ '{{print $2}}'"
    ).format(nic_netdst)
    return process.system_output(cmd, shell=True).decode().strip()


def get_pf_pci_address(vf_pci):
    """
    Get pf pci address using vf pci address.

    :param vf_pci: VF pci address
    :type vf_pci: str

    :return: VF pci address
    :rtype: str
    """
    cmd = (
        "grep PCI_SLOT_NAME /sys/bus/pci/devices/{0}/physfn/uevent | cut -d'=' -f2"
    ).format(vf_pci)
    return process.system_output(cmd, shell=True).decode().strip()


def get_pf_port(pf_pci):
    """
    Get the port for the pf pci address.

    :param pf_pci: PF pci address
    :type pf_pci: str

    :return: Port name
    :rtype: str
    """
    cmd = "ls /sys/bus/pci/devices/{0}/net/ | head -n 1".format(pf_pci)
    return process.system_output(cmd, shell=True).decode().strip()


def add_flows_to_ovs_bridge(bridge, ovs):
    """
    Add flow rules to the given ovs bridge.

    :parma bridge: OVS bridge name
    :type bridge: str
    :param ovs: OVS instance
    :type ovs: OpenVSwitch
    """
    utils_net.openflow_manager(
        bridge, "add-flow", flow_options="in_port=1,idle_timeout=0,actions=output:2"
    )
    utils_net.openflow_manager(
        bridge, "add-flow", flow_options="in_port=2,idle_timeout=0,actions=output:1"
    )
    utils_net.openflow_manager(bridge, "dump-flows")


class OVSHandler:
    def __init__(self, vm):
        self.vm = vm
        if check_ovs_status():
            self.ovs = openvswitch.OpenVSwitchControl()
        else:
            self.ovs = None

    def get_vdpa_ovs_info(self, add_flows=True, return_ports=True):
        """
        Get OVS bridge and port information.

        :param add_flows: Whether to add flows rules to the ovs bridge
        :type add_flows: bool
        :param return_ports: Whether to return port names
        :type return_ports: bool

        :return: list of target interfaces(bridges and ports) if return_port is Ture,
        else empty list
        :rtype: list
        """
        if not self.ovs:
            LOG_JOB.error("Could not find existing Open vSwitch service")
            return []

        target_ifaces = []

        for nic in self.vm.virtnet:
            ovs_br = None
            if nic.nettype == "vdpa":
                vf_pci = get_vf_pci_address(nic.netdst)
                pf_pci = get_pf_pci_address(vf_pci)
                port = get_pf_port(pf_pci)
                manager, ovs_br = utils_net.find_current_bridge(port)
            else:
                try:
                    manager, ovs_br = utils_net.find_current_bridge(nic.netdst)
                except NotImplementedError:
                    ovs_br = None
            if ovs_br:
                if add_flows:
                    add_flows_to_ovs_bridge(ovs_br, self.ovs)
                if return_ports:
                    if manager:
                        ports = set(manager.list_ports(ovs_br))
                        target_ifaces.extend(ports)
                    target_ifaces.append(ovs_br)

        return target_ifaces
