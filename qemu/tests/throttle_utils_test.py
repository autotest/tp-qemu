"""
Throttle utils test
"""
import logging
import time

from provider.block_devices_plug import BlockDevicesPlug
from provider.storage_benchmark import generate_instance

from virttest import error_context

from provider.throttle_utils import ThrottleGroupManager, ThrottleTester, \
    ThrottleGroupsTester


def utils_test(test, params, env, vm, session):
    """
    :param test:
    :param params:
    :param env:
    :param vm:
    :param session:
    :return:
    """
    logging.info(test, params, env, vm, session)
    tgm = ThrottleGroupManager(vm)

    logging.info("query_throttle_group group1")
    tgm.get_throttle_group_props("group1")

    logging.info("query_throttle_group group4")
    tgm.get_throttle_group_props("group4")
    # stg2 nonexist
    tgm.get_throttle_group_props("stg2")
    # group5 nonexist
    logging.info("delete_throttle_group group5")
    tgm.delete_throttle_group("group5")

    logging.info("query_throttle_group group3")
    tgm.get_throttle_group_props("group3")

    # add group3 failed
    logging.info("add_throttle_group group3")
    try:
        tgm.add_throttle_group("group3", {"iopsx-total": 50})
    except Exception as err:
        logging.error(err)

    # add group3 succeed
    tgm.add_throttle_group("group3", {"iops-total": 50})
    out = tgm.get_throttle_group_props("group3")
    logging.info(out)

    logging.info("get_throttle_group group3")
    dev = tgm.get_throttle_group("group3")

    plug = BlockDevicesPlug(vm)

    # hotplug stg6
    logging.info("stg6 hot-plug")
    plug.hotplug_devs_serial("stg6")
    logging.info(vm.devices.str_bus_short())

    logging.info("change stg6 from group3 to group1")
    tgm.change_throttle_group("stg6", "group1")
    logging.info("change stg3 from group1 to group2")
    tgm.change_throttle_group("stg3", "group2")
    logging.info(vm.devices.str_bus_short())
    logging.info("change stg3 from group2 to group1")
    tgm.change_throttle_group("stg3", "group1")
    logging.info(vm.devices.str_bus_short())
    vm.monitor.info("block")

    logging.info("stg6 hot-unplug")
    plug.unplug_devs_serial("stg6")
    logging.info(vm.devices.str_bus_short())

    logging.info("update throttle group")
    tgm.update_throttle_group("group3", {"bps-total": 150})
    out = tgm.get_throttle_group_props("group3")
    logging.info(out)
    logging.info(dev.raw_limits)

    logging.info("throttle group hot-unplug")
    tgm.delete_throttle_group("group3")
    logging.info(vm.devices.str_bus_short())
    tgm.get_throttle_group("group3")
    logging.info("==================")

    # image hotplug-unplug
    logging.info("unplug stg1 ")
    plug.unplug_devs_serial("stg1")
    logging.info(vm.devices.str_bus_short())

    logging.info("plug stg1")
    plug.hotplug_devs_serial("stg1")
    logging.info(vm.devices.str_bus_short())

    logging.info("unplug stg1")
    plug.unplug_devs_serial("stg1")
    logging.info(vm.devices.str_bus_short())

    logging.info("==================")
    logging.info("plug stg5 belong to no group")
    plug.hotplug_devs_serial("stg5")
    logging.info(vm.devices.str_bus_short())

    logging.info("unplug stg5")
    plug.unplug_devs_serial("stg5")
    logging.info(vm.devices.str_bus_short())
    logging.info("sleep 3...")
    time.sleep(3)

    logging.info("test simple_hotplug ...")
    image_name = "stg1"
    image_params = params.object_params(image_name)
    # include blockdevs and devices
    stg_a_devs = vm.devices.images_define_by_params(image_name,
                                                    image_params, 'disk')
    for dev in stg_a_devs:
        vm.devices.simple_hotplug(dev, vm.monitor)

    image_name = "stg5"
    image_params = params.object_params(image_name)
    stg_b_devs = vm.devices.images_define_by_params(image_name,
                                                    image_params, 'disk')
    for dev in stg_b_devs:
        vm.devices.simple_hotplug(dev, vm.monitor)
    logging.info(vm.devices.str_bus_short())
    time.sleep(3)

    logging.info("test simple_unplug ...")
    vm.devices.simple_unplug(stg_a_devs[-1], vm.monitor)
    vm.devices.simple_unplug(stg_b_devs[-1], vm.monitor)
    logging.info(vm.devices.str_bus_short())
    time.sleep(3)


def group_test(test, params, env, vm, session):
    """
    :param test:
    :param params:
    :param env:
    :param vm:
    :param session:
    :return:
    """
    logging.info(test, params, env, vm, session)
    tgm = ThrottleGroupManager(vm)
    tgm.get_throttle_group_props("group2")
    logging.info(vm.devices.str_bus_short())
    images = ["stg2", "stg4"]
    tester1 = ThrottleTester(test, params, vm, session, "group2",
                             images)
    tester1.build_default_option()
    images_info = tester1.build_images_fio_option()
    print(images_info)

    fio = generate_instance(params, vm, 'fio')
    tester1.set_fio(fio)
    # tester1.start()

    groups_tester = ThrottleGroupsTester([tester1])
    groups_tester.start()


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU 'Hello, throttle!' test

    """
    # Error contexts are used to give more info on what was
    # going on when one exception happened executing test code.
    error_context.context("Get the main VM", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    # logging.info(vm.devices.str_bus_long())
    session = vm.wait_for_login()
    logging.info(test.name)
    utils_test(test, params, env, vm, session)
    group_test(test, params, env, vm, session)
