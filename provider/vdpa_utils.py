from avocado.utils import process


def check_ovs_status():
    """
    Check if ovs-vsctl and openvswitch service are installed and running.

    :return:  True if both are available and running, otherwise False
    :rtype: bool
    """
    cmd = "which ovs-vsctl && systemctl status openvswitch.service"
    return process.system(cmd, ignore_status=True, shell=True) == 0


def get_ovs_bridges():
    """
    Get all ovs bridges.

    :return: List of ovs bridge names
    :rtype: list
    """
    cmd = "ovs-vsctl list-br"
    return process.system_output(cmd, shell=True).decode().split()


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


def get_ovs_bridge_for_port(port):
    """
    Get the ovs bridge name for the given network port.

    :param port: Network port name
    :type port: str

    :return: Bridge name
    :rtype: str
    """
    cmd = "ovs-vsctl port-to-br {0}".format(port)
    return process.system_output(cmd, shell=True).decode().strip()


def get_ovs_port_for_bridge(bridge):
    """
    Get the ovs port name for the given bridge port.

    :param bridge: Bridge name
    :type bridge: str

    :return: Port name
    :rtype: str
    """
    cmd = "ovs-vsctl list-ports {0}".format(bridge)
    return process.system_output(cmd, shell=True).decode().strip()


def get_vdpa_ovs_bridges(vm):
    """
    Get OVS bridge for VDPA devices in the VM.

    :param vm: Virtual machine object
    :type vm: object

    :return: OVS bridge name
    :rtype: str or None
    """
    for nic in vm.virtnet:
        if nic.nettype == "vdpa":
            vf_pci = get_vf_pci_address(nic.netdst)
            pf_pci = get_pf_pci_address(vf_pci)
            port = get_pf_port(pf_pci)
            return get_ovs_bridge_for_port(port)
    return None


def add_flows_to_ovs_bridge(bridge):
    """
    Add flow rules to the given ovs bridge.

    :parma bridge: OVS bridge name
    :type bridge: str
    """
    cmd = "ovs-ofctl add-flow {0} 'in_port=1,idle_timeout=0 actions=output:2'".format(
        bridge
    )
    cmd += (
        " && ovs-ofctl add-flow {0} 'in_port=2,idle_timeout=0 actions=output:1'".format(
            bridge
        )
    )
    cmd += " && ovs-ofctl dump-flows {0}".format(bridge)
    process.run(cmd, shell=True)


class OVSHandler:
    def __init__(self, vm):
        self.vm = vm

    def get_vdpa_ovs_info(self, add_flows=True, return_ports=True):
        """
        Get OVS bridge and port information.

        :param add_flows: Whether to add flows rules to the ovs bridge
        :type add_flows: bool
        :param return_ports: Whether to return port names
        :type return_port:bool

        :return: list of target interfaces(bridges and ports) if return_port is Ture,
        else empty list

        :rtype: list
        """
        if check_ovs_status():
            ovs_br_all = get_ovs_bridges()
            ovs_br = []
            target_ifaces = []

            vdpa_br = get_vdpa_ovs_bridges(self.vm)
            if vdpa_br:
                if add_flows:
                    add_flows_to_ovs_bridge(vdpa_br)
                ovs_br.append(vdpa_br)

            for nic in self.vm.virtnet:
                if nic.netdst in ovs_br_all:
                    ovs_br.append(nic.netdst)

            for br in ovs_br:
                ovs_port = get_ovs_port_for_bridge(br)
                if return_ports:
                    target_ifaces.extend(ovs_port.split() + [br])

            if return_ports:
                return target_ifaces
            else:
                return []
        else:
            return []
