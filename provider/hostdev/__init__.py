import logging
from pathlib import Path

from avocado.utils import process, wait
from virttest import utils_net

LOG_JOB = logging.getLogger("avocado.test")

PCI_PATH = Path("/sys/bus/pci/")
PCI_DEV_PATH = PCI_PATH / "devices"
PCI_DRV_PATH = PCI_PATH / "drivers"

# Refer to driverctl
DEV_CLASSES = {
    "storage": "01",
    "network": "02",
    "display": "03",
    "multimedia": "04",
    "memory": "05",
    "bridge": "06",
    "communication": "07",
    "system": "08",
    "input": "09",
    "docking": "0a",
    "processor": "0b",
    "serial": "0c",
}


class HostDeviceError(Exception):
    pass


class HostDeviceBindError(HostDeviceError):
    def __init__(self, slot_id, driver, error):
        self.slot_id = slot_id
        self.driver = driver
        self.error = error

    def __str__(self):
        return (
            f'Cannot bind "{self.slot_id}" to driver "{self.driver}": ' f"{self.error}"
        )


class HostDeviceUnbindError(HostDeviceBindError):
    def __init__(self, slot_id, driver, error):
        super().__init__(slot_id, driver, error)

    def __str__(self):
        return (
            f'Cannot unbind "{self.slot_id}" from driver "{self.driver}": '
            f"{self.error}"
        )


class VFCreateError(HostDeviceError):
    def __init__(self, slot_id, error):
        self.slot_id = slot_id
        self.error = error

    def __str__(self):
        return f"Failed to create VF devices for {self.slot_id}: {self.error}"


class PFDevice:
    def __init__(self, slot_id, driver):
        """
        Manages a physical function device for a given slot ID, configure its
        cycle via sysfs interface.

        Args:
            slot_id (str): The device slot ID, e.g.: '0000:01:00.0'
            driver (str): Driver to bind, e.g.: 'vfio-pci'
        """
        self.driver = driver
        self.slot_id = slot_id
        self.slot_path = PCI_DEV_PATH / self.slot_id
        self.origin_driver = self._get_current_driver(slot_id)
        self.pci_class = (self.slot_path / "class").read_text().strip()[2:4]
        self.device_id = (self.slot_path / "device").read_text().strip()[2:]
        self.vendor_id = (self.slot_path / "vendor").read_text().strip()[2:]
        if (
            self.pci_class == DEV_CLASSES["network"]
            and self.origin_driver != "vfio-pci"
        ):
            self.mac_addresses = [
                (nic / "address").read_text().strip()
                for nic in (self.slot_path / "net").iterdir()
            ]

    @staticmethod
    def _get_current_driver(slot_id):
        """
        Get the current used driver for the given slot

        Args:
            slot_id (str): The device slot ID

        Returns: The current driver name if exists, None otherwise
        """
        current_driver = PCI_DEV_PATH / slot_id / "driver"
        if current_driver.exists():
            return current_driver.resolve().name

    @property
    def same_iommu_group_devices(self):
        """
        Get all devices in the same iommu group

        Returns: All devices in the same iommu group from managed slot ID
        """
        return (self.slot_path / "iommu_group" / "devices").iterdir()

    def bind_all(self, driver):
        """
        Bind all devices to the driver, takes a list of device locations
        """
        group_devices = self.same_iommu_group_devices
        for dev in group_devices:
            self.bind_one(dev.name, driver)

    def bind_one(self, slot_id, driver):
        """
        Bind the device given by "slot_id" to the driver "driver". If the
        device is already bound to a different driver, it will be unbound first
        """
        current_driver = self._get_current_driver(slot_id)
        if current_driver:
            if current_driver == driver:
                LOG_JOB.info(
                    "Notice: %s already bound to driver %s, skipping", slot_id, driver
                )
                return
            self.unbind_one(slot_id)
        LOG_JOB.info("Binding driver for device %s", slot_id)
        # For kernels >= 3.15 driver_override can be used to specify the driver
        # for a device rather than relying on the driver to provide a positive
        # match of the device.
        override_file = PCI_DEV_PATH / slot_id / "driver_override"
        if override_file.exists():
            try:
                override_file.write_text(driver)
            except OSError as e:
                raise HostDeviceError(
                    f"Failed to set the driver " f"override for {slot_id}:  {str(e)}"
                )
        # For kernels < 3.15 use new_id to add PCI id's to the driver
        else:
            id_file = PCI_DRV_PATH / driver / "new_id"
            try:
                id_file.write_text(f"{self.vendor_id} {self.device_id}")
            except OSError as e:
                raise HostDeviceError(
                    f"Failed to assign the new ID of {slot_id} for driver "
                    f"{driver}: {str(e)}"
                )

        # Bind to the driver
        try:
            with (PCI_DRV_PATH / driver / "bind").open("a") as bind_f:
                bind_f.write(slot_id)
        except OSError as e:
            raise HostDeviceBindError(slot_id, driver, str(e))

        # Before unbinding it, overwrite driver_override with empty string so
        # that the device can be bound to any other driver
        if override_file.exists():
            try:
                override_file.write_text("\00")
            except OSError as e:
                raise HostDeviceError(
                    f'{slot_id} refused to restore "driver_override" to empty '
                    f"string: {str(e)}"
                )

    def config(self, params):
        """
        Load the driver module and bind all devices to the driver. If users
        want to customize the module parameters, they should reload it
        themselves.

        Args:
            params (virttest.utils_params.Params): params to configure module
        """
        self.bind_all(self.driver)

    def restore(self):
        """
        Unload the module and restore the device at the end of the test cycle
        """
        if self.origin_driver:
            self.bind_all(self.origin_driver)

    def unbind_one(self, slot_id):
        """
        Unbind the device identified by "slot_id" from its current driver
        """
        current_driver = self._get_current_driver(slot_id)
        if current_driver:
            LOG_JOB.info('Unbinding current driver "%s"', current_driver)
            driver_path = PCI_DRV_PATH / current_driver
            try:
                with (driver_path / "unbind").open("a") as unbind_f:
                    unbind_f.write(slot_id)
            except OSError as e:
                HostDeviceUnbindError(slot_id, current_driver, str(e))


class VFDevice(PFDevice):
    def __init__(self, slot_id, driver):
        """
        Manages a virtual function device for a given slot ID, configure its
        cycle via sysfs interface.

        Args:
            slot_id (str): The device slot ID, e.g.: '0000:01:00.0'
            driver (str): Driver to bind, e.g.: 'vfio-pci'
        """
        super().__init__(slot_id, driver)
        self.num_vfs = 0
        self.vfs = []
        self.sriov_numvfs_path = self.slot_path / "sriov_numvfs"

    def _config_net_vfs(self, params):
        """
        Configure all VFs after created, assigning them to have a specific MAC
        address instead of using the default "00:00:00:00:00:00"
        Args:
            params (virttest.utils_params.Params): params to configure VFs
        """
        self.mac_addresses = []
        dev_name = next((self.slot_path / "net").iterdir()).name
        for idx, vf in enumerate(self.vfs):
            mac = params.get(
                f"hostdev_vf{idx}_mac", utils_net.generate_mac_address_simple()
            )
            self.mac_addresses.append(mac)
            LOG_JOB.info('Assigning MAC address "%s" to VF "%s"', mac, vf)
            process.run(f"ip link set dev {dev_name} vf {idx} mac {mac}")

    def bind_all(self, driver):
        """
        Override this method to bind all VFs to the driver
        """
        for dev in self.vfs:
            self.bind_one(dev, driver)

    def config(self, params):
        """
        Override this method to create VFs first, and if the PF is NIC, then
        configure all VFs with fixed MAC address
        """
        vf_counts = params.get_numeric("hostdev_vf_counts")
        self.create_vfs(vf_counts)
        super().config(params)
        if (self.slot_path / "class").read_text()[2:4] == "02":
            LOG_JOB.info(
                'Device "%s" is a network device, configure MAC address for VFs',
                self.slot_id,
            )
            self._config_net_vfs(params)

    def create_vfs(self, counts):
        """
        Create a set number of VFs by "counts"

        Args:
            counts (int): Number of VFs to create
        """
        if self._get_current_driver(self.slot_id) == "vfio-pci":
            raise VFCreateError(
                self.slot_id,
                f'Slot "{self.slot_id}" is bound to '
                f'"vfio-pci", please fall back to kernel driver '
                f"to create VFs",
            )
        try:
            if counts > int((self.slot_path / "sriov_totalvfs").read_text().strip()):
                raise VFCreateError(
                    self.slot_id,
                    "Count of VF to be created is " 'larger than "sriov_totalvfs"',
                )
            self.num_vfs = int(self.sriov_numvfs_path.read_text().strip())
            with self.sriov_numvfs_path.open("w") as numvfs_f:
                if self.num_vfs != 0:
                    numvfs_f.write("0")
                    numvfs_f.flush()
                numvfs_f.write(str(counts))
        except OSError as e:
            raise VFCreateError(self.slot_id, str(e))
        wait.wait_for(
            lambda: len(list(self.slot_path.glob("virtfn*"))) == counts,
            timeout=(counts * 10),
        )

        vfs = sorted(list(self.slot_path.glob("virtfn*")))
        self.vfs = [vf.resolve().name for vf in vfs]

    def restore(self):
        """
        Unload the module and restore the device at the end of the test cycle
        """
        super().restore()
        self.create_vfs(self.num_vfs)
