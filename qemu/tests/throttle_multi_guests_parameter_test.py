import os
import shutil

from virttest import data_dir, env_process, error_context, qemu_storage, utils_misc

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

    def copy_base_vm_image():
        """Copy the base vm image for VMs."""
        src_img = qemu_storage.QemuImg(
            params, data_dir.get_data_dir(), params["images"]
        )
        src_filename = src_img.image_filename
        src_format = src_img.image_format
        dst_dir = os.path.dirname(src_filename)
        for vm_name in vms_list:
            dst_filename = os.path.join(dst_dir, "%s.%s" % (vm_name, src_format))
            if not os.path.exists(dst_filename):
                test.log.info("Copying %s to %s.", src_filename, dst_filename)
                shutil.copy(src_filename, dst_filename)

    def wait_for_login_all_vms():
        """Wait all VMs to login."""
        return [vm.wait_for_login() for vm in vms]

    @error_context.context_aware
    def fio_on_vm(vm_t, session_t):
        error_context.context("Deploy fio", test.log.info)
        fio = generate_instance(params, vm_t, "fio")
        test.log.info("fio: %s", fio)
        tgm = ThrottleGroupManager(vm_t)
        test.log.info("tgm: %s", tgm)
        groups = params["throttle_groups"].split()
        testers = []
        for group in groups:
            tgm.get_throttle_group_props(group)
            images = params["throttle_group_member_%s" % group].split()
            tester = ThrottleTester(test, params, vm_t, session_t, group, images)
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

    def fio_on_vms():
        """Run fio on all started vms at the same time."""
        test.log.info("Start to do fio on  multi-vms:")
        fio_parallel_params = []
        for vm, session in zip(vms, sessions):
            fio_parallel_params.append((fio_on_vm, (vm, session)))
        utils_misc.parallel(fio_parallel_params)
        test.log.info("Done fio on multi-vms.")

    vms_list = params["vms"].split()
    copy_base_vm_image()
    vms_default = params["vms"].split()[0]
    vms_post = params["vms"].split(vms_default)[1].strip()
    params["vms"] = str(vms_post)
    params["start_vm"] = "yes"
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )
    vms = env.get_all_vms()
    for vm_verify in vms:
        vm_verify.verify_alive()
    sessions = wait_for_login_all_vms()
    fio_on_vms()
