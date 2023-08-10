import json
import logging
import os
import pathlib
import time

from aexpect.remote import wait_for_login

from virttest import utils_misc
from virttest import utils_net
from virttest.qemu_devices.qdevices import QDevice
from virttest.qemu_devices.utils import set_cmdline_format_by_cfg
from virttest.virt_vm import VMDeviceNotSupportedError

from provider.hostdev import PCI_DEV_PATH, PCI_DRV_PATH, DEV_CLASSES

LOG_JOB = logging.getLogger('avocado.test')


def hostdev_define_by_params(name, params, host, bus=None):
    """
    Define a host device based on the provided parameters.

    Args:
        name (str): The device name to be defined.
        params (virttest.utils_params.Params): The device parameters.
        host (str): The host device PCI slot identifier.
        bus: (dict): The bus configuration where the device should be attached.

    Returns:
        virttest.qemu_devices.qdevices.QDevice: The defined device object.
    """
    driver = params.get('vm_hostdev_driver')
    dev_params = {
        'driver': driver,
        'id': name,
        'host': host,
        'failover_pair_id': params.get("vm_hostdev_failover_pair_id")
    }
    # TODO: Support vfio-ap and vfio-ccw, currently only for pci devices
    bus = bus or {'aobject': params.get('pci_bus', 'pci.0')}
    dev = QDevice(driver, dev_params, parent_bus=bus)
    for ext_k, ext_v in params.get_dict("vm_hostdev_extra_params").items():
        dev.set_param(ext_k, ext_v)
    return dev


def insert_hostdev_to_vm(vm, name, host, bus=None):
    """
    Insert a host device into a virtual machine (VM) based on the provided parameters.

    Args:
        vm (virttest.qemu_vm.VM): The VM object representing the virtual machine.
        name (str): The device name (qid) to be defined within the VM.
        host (str): The host device PCI slot identifier.
        bus (dict): The bus configuration where the device should be attached.
    """
    params = vm.params.object_params(name)
    driver = params.get('vm_hostdev_driver')
    if not vm.devices.has_device(driver):
        raise VMDeviceNotSupportedError(vm.name, driver)
    dev = hostdev_define_by_params(name, params, host, bus)
    get_cmdline_format_cfg = getattr(vm, '_get_cmdline_format_cfg')
    set_cmdline_format_by_cfg(dev, get_cmdline_format_cfg(), 'hostdevs')
    vm.devices.insert(dev)
    dev_bus = vm.devices.get_by_params({'id': dev.get_param('bus')})
    if dev_bus and dev_bus[0].get_param("driver") == "pcie-root-port":
        set_cmdline_format_by_cfg(dev_bus[0], get_cmdline_format_cfg(), 'pcic')


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
    for dev_path in pathlib.Path(PCI_DEV_PATH).iterdir():
        with open(os.path.join(dev_path, 'class'), 'r') as class_f:
            if class_f.read()[2:4] != class_id:
                continue
            pci_ids.add(os.path.basename(dev_path))
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
    driver_path = pathlib.Path(os.path.join(PCI_DRV_PATH, driver))
    pci_ids = {pci_path.name for pci_path in
               driver_path.glob('**/[0-9a-z]*:[0-9a-z]*:[0-9a-z]*.[0-9a-z]*')}
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
    if dev_type not in ['pf', 'vf']:
        raise ValueError(f'Device type({dev_type}) must be "pf" or "vf"')
    pf_pci_ids = []
    vf_pci_ids = []
    pci_ids = get_pci_by_class(dev_class, driver)
    for pci in pci_ids:
        if os.path.exists(os.path.join(PCI_DEV_PATH, pci, 'physfn')):
            vf_pci_ids.append(pci)
        else:
            pf_pci_ids.append(pci)

    return pf_pci_ids if dev_type == 'pf' else vf_pci_ids


def get_parent_slot(slot_id):
    """
    Get the device parent id. If it's a VF device, return the physical parent
    device ID. Otherwise, return the slot_id itself.

    Args:
        slot_id (str): The device slot ID, e.g.: '0000:01:00.0'

    Returns: The parent slot id
    """
    parent_path = os.path.realpath(
        os.path.join(PCI_DEV_PATH, slot_id, 'physfn'))
    if os.path.exists(parent_path):
        return os.path.basename(parent_path)
    return slot_id


def get_ifname_from_pci(pci_slot):
    """
    Get the NIC device name from its pci slot id.

    Args:
        pci_slot (str): The slot id of the NIC device

    Returns: The NIC name from its pci slot

    """
    pci_net_path = os.path.join(PCI_DEV_PATH, pci_slot, 'net')
    if os.path.exists(pci_net_path):
        try:
            return os.listdir(os.path.join(PCI_DEV_PATH, pci_slot, 'net'))[0]
        except OSError as e:
            LOG_JOB.error(f'Cannot get the NIC name of {pci_slot}: str({e})')
            return ''


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
    ip_addr = ''
    os_type = vm.params['os_type']
    serial_session = vm.wait_for_serial_login()

    try:
        if os_type == 'linux':
            addr_family = 'inet' if ip_version == 4 else 'inet6'
            for ifname in utils_net.get_linux_ifname(serial_session):
                nic_info = json.loads(serial_session.cmd_output_safe(
                    f'ip -j link show {ifname}'))[0]
                if nic_info['address'] == mac:
                    if ('(disconnected)' in
                            serial_session.cmd_output_safe(
                                f'nmcli -g GENERAL.STATE device show {ifname}')):
                        serial_session.cmd(f'nmcli device up {ifname}')
                    ip_info = json.loads(serial_session.cmd_output_safe(
                        f'ip -j addr show {ifname}'))[0]
                    for addr_info in ip_info['addr_info']:
                        if (addr_info['family'] == addr_family and
                                addr_info['scope'] == 'global'):
                            ip_addr = addr_info['local']
                else:
                    if ('(connected)' in
                            serial_session.cmd_output_safe(
                                f'nmcli -g GENERAL.STATE device show {ifname}')):
                        serial_session.cmd(f'nmcli device down {ifname}')
        elif os_type == "windows":
            ifname = utils_net.get_windows_nic_attribute(
                serial_session, "macaddress", mac, "netconnectionid")
            utils_net.enable_windows_guest_network(serial_session, ifname)
            nic_info = utils_net.get_net_if_addrs_win(serial_session, mac)
            ip_addr = nic_info['ipv4'] if ip_version == 4 else nic_info['ipv6']
        else:
            raise ValueError("Unknown os type")
    finally:
        serial_session.close()
    LOG_JOB.info(f'IP address of MAC address({mac}) is: {ip_addr}')
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
        linesep = vm.params.get(
            "shell_linesep", "\n").encode().decode('unicode_escape')
        log_filename = (f'session-{vm.name}-{time.strftime("%m-%d-%H-%M-%S")}-'
                        f'{utils_misc.generate_random_string(4)}.log')
        log_filename = utils_misc.get_log_filename(log_filename)
        log_function = utils_misc.log_line
        return wait_for_login('ssh',
                              ip_addr,
                              port,
                              username,
                              password,
                              prompt,
                              linesep,
                              log_filename,
                              log_function)
