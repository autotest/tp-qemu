import logging
from contextlib import contextmanager

from virttest import utils_kernel_module

from provider import hostdev
from provider.hostdev.utils import PCI_DEV_PATH

LOG_JOB = logging.getLogger("avocado.test")


def config_hostdev(slot_id, params):
    """
    Configure a host device with given parameters.

    Args:
        slot_id (str): The device slot ID, e.g.: '0000:01:00.0'
        params (virttest.utils_params.Params): params to configure the hostdev

    Returns: The hostdev object
    """
    bind_driver = params.get("hostdev_bind_driver")
    driver_module = utils_kernel_module.KernelModuleHandler(bind_driver)
    module_params = params.get("hostdev_driver_module_params", "")
    if not driver_module.was_loaded:
        driver_module.reload_module(True, module_params)
    dev_type = params.get("hostdev_assignment_type", "pf")
    if dev_type == "pf":
        host_dev = hostdev.PFDevice(slot_id, bind_driver)
    elif dev_type == "vf":
        host_dev = hostdev.VFDevice(slot_id, bind_driver)
    else:
        raise NotImplementedError(f'Device type "{dev_type}" is not supported')
    host_dev.config(params)
    return host_dev


@contextmanager
def hostdev_setup(params):
    """
    Set up all host devices to prepare the test environment.

    Args:
        params (virttest.utils_params.Params): Dict of the test parameters
    """
    # Get all host pci slots that need to be set up
    host_pci_slots = params.objects("setup_hostdev_slots")
    host_devs = []
    # Set up host devices
    for slot in host_pci_slots:
        if not (PCI_DEV_PATH / slot).exists():
            LOG_JOB.warning(
                "The provided slot(%s) does not exist, skipping setup it.", slot
            )
            continue
        hostdev_params = params.object_params(slot)
        host_dev = config_hostdev(slot, hostdev_params)
        host_devs.append(host_dev)
        params[f"hostdev_manager_{slot}"] = host_dev

    try:
        yield params
    finally:
        for dev in reversed(host_devs):
            dev.restore()
