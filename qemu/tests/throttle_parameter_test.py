import time

from virttest import error_context

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
    There are two throttle groups and each have two disk
    2) Build fio operation options and expected result
     according to throttle properties.
    3) Execute one disk or all disks testing on groups parallel.
    """

    error_context.context("Get the main VM", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=360)
    time.sleep(20)

    error_context.context("Deploy fio", test.log.info)
    fio = generate_instance(params, vm, "fio")

    tgm = ThrottleGroupManager(vm)
    groups = params["throttle_groups"].split()
    testers = []
    for group in groups:
        tgm.get_throttle_group_props(group)
        images = params["throttle_group_member_%s" % group].split()
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

    groups_tester.start()
