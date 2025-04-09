from avocado.utils import process


def check_ovs_status():
    """
    Check if ovs-vsctl and openvswitch service are installed and running.
    Returns True if both are available and running, otherwise False.
    """
    cmd = "which ovs-vsctl && systemctl status openvswitch.service"
    return process.system(cmd, ignore_status=True, shell=True) == 0


def get_ovs_bridges():
    """
    Get all ovs bridges.
    Returns a list of ovs bridge names.
    """
    cmd = "ovs-vsctl list-br"
    return process.system_output(cmd, shell=True).decode().split()


def get_vf_pci_address(nic_netdst):
    """
    Get vf pci address from a given network destination.
    Returns the vf pci address as a string.
    """
    cmd = (
        "vdpa dev show | grep {0} | grep -o 'pci/[^[:space:]]*' | "
        "awk -F/ '{{print $2}}'"
    ).format(nic_netdst)
    return process.system_output(cmd, shell=True).decode().strip()


def get_pf_pci_address(vf_pci):
    """
    Get pf pci address using vf pci address.
    Returns the pf pci address as a string.
    """
    cmd = (
        "grep PCI_SLOT_NAME /sys/bus/pci/devices/{0}/physfn/uevent | cut -d'=' -f2"
    ).format(vf_pci)
    return process.system_output(cmd, shell=True).decode().strip()


def get_pf_port(pf_pci):
    """
    Get the port for the pf pci address.
    Returns the port name.
    """
    cmd = "ls /sys/bus/pci/devices/{0}/net/ | head -n 1".format(pf_pci)
    return process.system_output(cmd, shell=True).decode().strip()


def get_ovs_bridge_for_port(port):
    """
    Get the ovs bridge name for the given network port.
    Returns the bridge name.
    """
    cmd = "ovs-vsctl port-to-br {0}".format(port)
    return process.system_output(cmd, shell=True).decode().strip()


def get_ovs_port_for_bridge(bridge):
    """
    Get the ovs port name for the given bridge port.
    Returns the bridge name.
    """
    cmd = "ovs-vsctl list-ports {0}".format(bridge)
    return process.system_output(cmd, shell=True).decode().strip()


def get_vdpa_ovs_bridges(vm):
    """
    Get OVS bridge for VDPA devices in the VM.
    Returns the OVS bridge name, or None if not found.
    """
    for nic in vm.virtnet:
        if nic.nettype == "vdpa":
            vf_pci = get_vf_pci_address(nic.netdst)
            pf_pci = get_pf_pci_address(vf_pci)
            port = get_pf_port(pf_pci)
            return get_ovs_bridge_for_port(port)
    return None


def add_flows_to_ovs_bridge(br):
    """
    Add flow rules to the given ovs bridge.
    """
    cmd = "ovs-ofctl add-flow {0} 'in_port=1,idle_timeout=0 actions=output:2'".format(
        br
    )
    cmd += (
        " && ovs-ofctl add-flow {0} 'in_port=2,idle_timeout=0 actions=output:1'".format(
            br
        )
    )
    cmd += " && ovs-ofctl dump-flows {0}".format(br)
    process.run(cmd, shell=True)


class OVSHandler:
    def __init__(self, vm):
        self.vm = vm

    def get_vdpa_ovs_info(self, add_flows=True, return_ports=True):
        """
        Get OVS bridge and port information
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
