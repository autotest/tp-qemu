import json

from virttest import data_dir, qemu_storage

from provider import backup_utils, block_dirty_bitmap, job_utils
from provider.virt_storage.storage_admin import sp_admin


def run(test, params, env):
    """
    backup VM disk test:

    1) start VM with data disk
    2) create target disk with qmp command
    3) full backup source disk to target disk with 65535 persistent bitmaps
    4) shutdown VM
    5) verify bitmap save to data disk
    6) boot VM with data disk to check bitmaps with qmp cmd query-block
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def full_backup(vm, source_node, target_node, bitmap_count):
        """start full backup job with 65535 bitmaps"""

        test.log.info("Begin full backup %s to %s", source_node, target_node)
        actions, extra_options = [], {"sync": "full"}
        cmd, args = backup_utils.blockdev_backup_qmp_cmd(
            source_node, target_node, **extra_options
        )
        backup_action = {"type": cmd, "data": args}
        actions.append(backup_action)
        bitmap_data = {"node": source_node, "persistent": True}
        for idx in range(0, bitmap_count):
            data = bitmap_data.copy()
            data["name"] = "bitmap_%d" % idx
            action = {"type": "block-dirty-bitmap-add", "data": data}
            actions.append(action)
        vm.monitor.cmd("transaction", {"actions": actions})
        job_utils.wait_until_block_job_completed(vm, args["job-id"])

    def verify_bitmap_counts(vm, source_node, bitmap_count):
        """Verify bitmap count after backup job is start"""

        test.log.info("Verify bitmap counts in device '%s'", source_node)
        out = vm.monitor.query("block")
        bitmaps_dict = block_dirty_bitmap.get_bitmaps(out)
        if source_node not in bitmaps_dict:
            raise test.fail("device '%s' not found!" % source_node)
        bitmap_len = len(bitmaps_dict[source_node])
        msg = "bitmap count mismatch, %s != %s" % (bitmap_len, bitmap_count)
        assert bitmap_len == bitmap_count, msg

    def verify_persistent_bitmaps(params, image_name, bitmap_count):
        """Verify bitmap count by qemu-img command"""

        test.log.info("Verify bitmaps info save in image '%s'", image_name)
        image_dir = data_dir.get_data_dir()
        image_params = params.object_params(image_name)
        data_img = qemu_storage.QemuImg(image_params, image_dir, image_name)
        output = data_img.info(output="json")
        info = json.loads(output)
        bitmap_len = len(info["format-specific"]["data"]["bitmaps"])
        msg = "bitmap losts after destory VM, %s != %s" % (bitmap_len, bitmap_count)
        assert bitmap_len == bitmap_count, msg

    source_image = params.get("source_image")
    target_image = params.get("target_image")
    source_node = "drive_%s" % source_image
    target_node = "drive_%s" % target_image
    bitmap_count = int(params.get("bitmap_count", 65535))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    params.setdefault("target_path", data_dir.get_data_dir())
    target_disk = sp_admin.volume_define_by_params(target_image, params)
    target_disk.hotplug(vm)
    full_backup(vm, source_node, target_node, bitmap_count)
    verify_bitmap_counts(vm, source_node, bitmap_count)
    vm.destroy()
    verify_persistent_bitmaps(params, source_image, bitmap_count)
    vm = env.get_vm(params["main_vm"])
    vm.create()
    vm.verify_alive()
    verify_bitmap_counts(vm, source_node, bitmap_count)
