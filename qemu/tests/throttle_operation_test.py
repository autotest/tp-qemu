"""IO-Throttling group and other operation relevant testing"""

import json
import time

from virttest import error_context
from virttest.qemu_monitor import QMPCmdError

from provider.block_devices_plug import BlockDevicesPlug
from provider.blockdev_snapshot_base import BlockDevSnapshotTest
from provider.storage_benchmark import generate_instance
from provider.throttle_utils import (
    ThrottleGroupManager,
    ThrottleGroupsTester,
    ThrottleTester,
)


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Test throttle relevant properties feature.

    1) Boot up guest with throttle groups.
    There are two throttle groups. One have two disks,other is empty.
    2) Build fio operation options and expected result
     according to throttle properties.
    3) Execute single disk throttle testing on  first group.
    4) Execute group relevant testing for example:
    Change throttle group attribute or move disk to other group
    5) Or Execute other operation testing for example:
    Reboot guest or stop-resume guest
    or add snapshot on throttle node
    6) Execute throttle testing on all groups.
    """

    def negative_test():
        """negative test for the group option"""
        all_groups = params.get("groups", "group2")
        for name in all_groups.split():
            props = json.loads(params.get(name, "{}"))
            err_msg = params.object_params(name)["err_msg"]
            try:
                tgm.update_throttle_group("group1", props)
            except QMPCmdError as err:
                qmp_desc = err.data["desc"]
                if qmp_desc.find(err_msg) >= 0:
                    test.log.info("Find expected result for %s", name)
                    continue
                test.log.error(
                    "Cannot got expected wrong result on %s: %s in %s",
                    name,
                    err_msg,
                    qmp_desc,
                )
                raise err
            else:
                test.fail("Can not got expected wrong result")

    def group_change():
        """change group attributes testing"""
        props = json.loads(params["throttle_group_parameters_group2"])

        tgm.update_throttle_group("group1", props)

    def group_move():
        """Move disk to other group"""
        tgm.change_throttle_group("stg2", "group2")

    def operation_reboot():
        """Guest reboot test"""
        vm.reboot(session)

    def operation_stop_resume():
        """Guest stop resume test"""
        vm.pause()
        vm.resume()

    def operation_hotplug():
        """
        relevant operation:
        unplug throttle group
        plug throttle group
        add disk into exist throttle group
        add disk into plugged throttle group
        """
        opts = json.loads(params.get("throttle_group_parameters_group2", "{}"))
        tgm.delete_throttle_group("group2")
        tgm.add_throttle_group("group2", opts)
        plug = BlockDevicesPlug(vm)
        plug.hotplug_devs_serial("stg3")
        plug.hotplug_devs_serial("stg4")

    def operation_snapshot():
        """
        define snapshot node name, create snapshot
        """
        params["node"] = params["image_format"] + "_" + params["base_tag"]
        snapshot_test = BlockDevSnapshotTest(test, params, env)
        snapshot_test.prepare_snapshot_file()
        snapshot_test.create_snapshot()

    error_context.context("Get the main VM", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=360)
    time.sleep(20)

    error_context.context("Deploy fio", test.log.info)
    fio = generate_instance(params, vm, "fio")

    tgm = ThrottleGroupManager(vm)
    groups = params["throttle_groups"].split()
    operation = params["operation"]

    # simple test on group1
    error_context.context("Execute simple test on group1", test.log.info)
    tester = ThrottleTester(test, params, vm, session, "group1", ["stg1"])
    tester.build_default_option()
    tester.build_images_fio_option()
    tester.set_fio(fio)
    tester.start()

    # execute relevant operation
    error_context.context("Execute operation %s" % operation, test.log.info)
    locals_var = locals()
    locals_var[operation]()
    # test after operation
    testers = []
    tgm = ThrottleGroupManager(vm)
    session = vm.wait_for_login(timeout=360)
    for group in groups:
        tgm.get_throttle_group_props(group)
        images = params.get("throttle_group_member_%s" % group, "").split()
        if len(images) == 0:
            test.log.info("No images in group %s", group)
            continue
        tester = ThrottleTester(test, params, vm, session, group, images)
        error_context.context(
            "Build test stuff for %s:%s" % (group, images), test.log.info
        )
        tester.build_default_option()
        tester.build_images_fio_option()
        tester.set_fio(fio)
        testers.append(tester)

    error_context.context("Start groups testing:%s" % groups, test.log.info)
    groups_tester = ThrottleGroupsTester(testers)

    repeat_test = params.get_numeric("repeat_test", 1)
    for repeat in range(repeat_test):
        error_context.context("Begin test loop:%d" % repeat, test.log.info)
        groups_tester.start()
