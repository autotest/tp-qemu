import json
import logging
import time

from aexpect.remote import wait_for_login
from virttest import utils_misc, utils_net

from provider.hostdev import DEV_CLASSES, PCI_DEV_PATH, PCI_DRV_PATH

LOG_JOB = logging.getLogger("avocado.test")


def get_pci_by_class(dev_class, driver=None):
    """
    Get device pci slots by given device type and driver

    Args:
        dev_class (str): The device class type, e.g.: "network"
        driver (str): Driver used by devices

    Returns: A list of all matched devices
    """
    pci_ids = set()
    class_id = DEV_CLASSES.get(dev_class)
    for dev_path in PCI_DEV_PATH.iterdir():
        if dev_path.joinpath("class").read_text()[2:4] != class_id:
            continue
        pci_ids.add(dev_path.name)
    if driver:
        pci_ids &= set(get_pci_by_driver(driver))
    return sorted(pci_ids)


def get_pci_by_driver(driver):
    """
    Get device pci slots by given driver

    Args:
        driver (str): Driver used by devices

    Returns: A list of all matched devices
    """
    driver_path = PCI_DRV_PATH / driver
    pci_ids = {
        pci_path.name
        for pci_path in driver_path.glob("**/[0-9a-z]*:[0-9a-z]*:[0-9a-z]*.[0-9a-z]*")
    }
    return sorted(pci_ids)


def get_pci_by_dev_type(dev_type, dev_class, driver=None):
    """

    Args:
        dev_type (str): "pf" or "vf" you want to filter
        dev_class: The device class type, e.g.: "network"
        driver: Driver used by devices

    Returns: A list of all matched devices

    """
    dev_type = dev_type.lower()
    if dev_type not in ["pf", "vf"]:
        raise ValueError(f'Device type({dev_type}) must be "pf" or "vf"')
    pf_pci_ids = []
    vf_pci_ids = []
    pci_ids = get_pci_by_class(dev_class, driver)
    for pci in pci_ids:
        if PCI_DEV_PATH.joinpath(pci, "physfn").exists():
            vf_pci_ids.append(pci)
        else:
            pf_pci_ids.append(pci)

    return pf_pci_ids if dev_type == "pf" else vf_pci_ids


def get_parent_slot(slot_id):
    """
    Get the device parent id. If it's a VF device, return the physical parent
    device ID. Otherwise, return the slot_id itself.

    Args:
        slot_id (str): The device slot ID, e.g.: '0000:01:00.0'

    Returns: The parent slot id
    """
    physfn_path = PCI_DEV_PATH / slot_id / "physfn"
    if physfn_path.exists():
        return physfn_path.resolve().name
    return slot_id


def get_ifname_from_pci(pci_slot):
    """
    Get the NIC device name from its pci slot id.

    Args:
        pci_slot (str): The slot id of the NIC device

    Returns: The NIC name from its pci slot

    """
    pci_net_path = PCI_DEV_PATH / pci_slot / "net"
    if pci_net_path.exists():
        try:
            return next((PCI_DEV_PATH / pci_slot / "net").iterdir()).name
        except OSError as e:
            LOG_JOB.error("Cannot get the NIC name of %s: %s", pci_slot, str(e))
            return ""


def get_guest_ip_from_mac(vm, mac, ip_version=4):
    """
    Get IP address from MAC address with selected IP version

    Args:
        vm (virttest.qemu_vm.VM): The vm object
        mac (str): The MAC address of the VM's network interface
        ip_version (int): IP version to use for connecting (default is IPv4)

    Returns: The IP address if found
    """
    if ip_version not in [4, 6]:
        raise ValueError(f"Unsupported IP version: {ip_version}")
    ip_addr = ""
    os_type = vm.params["os_type"]
    serial_session = vm.wait_for_serial_login()

    try:
        if os_type == "linux":
            addr_family = "inet" if ip_version == 4 else "inet6"
            for ifname in utils_net.get_linux_ifname(serial_session):
                nic_info = json.loads(
                    serial_session.cmd_output_safe(f"ip -j link show {ifname}")
                )[0]
                if nic_info["address"] == mac:
                    if "(disconnected)" in serial_session.cmd_output_safe(
                        f"nmcli -g GENERAL.STATE device show {ifname}"
                    ):
                        serial_session.cmd(f"nmcli device up {ifname}")
                    ip_info = json.loads(
                        serial_session.cmd_output_safe(f"ip -j addr show {ifname}")
                    )[0]
                    for addr_info in ip_info["addr_info"]:
                        if (
                            addr_info["family"] == addr_family
                            and addr_info["scope"] == "global"
                        ):
                            ip_addr = addr_info["local"]
                else:
                    if "(connected)" in serial_session.cmd_output_safe(
                        f"nmcli -g GENERAL.STATE device show {ifname}"
                    ):
                        serial_session.cmd(f"nmcli device down {ifname}")
        elif os_type == "windows":
            ifname = utils_net.get_windows_nic_attribute(
                serial_session, "macaddress", mac, "netconnectionid"
            )
            utils_net.enable_windows_guest_network(serial_session, ifname)
            nic_info = utils_net.get_net_if_addrs_win(serial_session, mac)
            ip_addr = nic_info["ipv4"] if ip_version == 4 else nic_info["ipv6"]
        else:
            raise ValueError("Unknown os type")
    finally:
        serial_session.close()
    LOG_JOB.info("IP address of MAC address(%s) is: %s", mac, ip_addr)
    return ip_addr


def ssh_login_from_mac(vm, mac, ip_version=4):
    """
    Establish an SSH login session to a VM using its MAC address.

    Args:
        vm (virttest.qemu_vm.VM): The vm object
        mac (str): The MAC address of the VM's network interface
        ip_version (int): IP version to use for connecting (default is IPv4)

    Returns: The ssh session object
    """
    ip_addr = get_guest_ip_from_mac(vm, mac, ip_version)
    if ip_addr:
        username = vm.params.get("username", "")
        password = vm.params.get("password", "")
        prompt = vm.params.get("shell_prompt", r"[\#\$]\s*$")
        port = vm.params.get("shell_port")
        linesep = vm.params.get("shell_linesep", "\n").encode().decode("unicode_escape")
        log_filename = (
            f'session-{vm.name}-{time.strftime("%m-%d-%H-%M-%S")}-'
            f"{utils_misc.generate_random_string(4)}.log"
        )
        log_filename = utils_misc.get_log_filename(log_filename)
        log_function = utils_misc.log_line
        return wait_for_login(
            "ssh",
            ip_addr,
            port,
            username,
            password,
            prompt,
            linesep,
            log_filename,
            log_function,
        )
