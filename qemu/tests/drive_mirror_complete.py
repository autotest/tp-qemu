from virttest import data_dir, env_process, error_context, qemu_storage

from qemu.tests import drive_mirror


@error_context.context_aware
def run(test, params, env):
    """
    Test block mirroring functionality

    1). boot vm, then mirror $source_image to $target_image
    2). wait for mirroring job go into ready status
    3). pause vm after vm in ready status
    4). reopen $target_image file
    5). compare $source image and $target_image file
    6). resume vm
    7). boot vm from $target_image and check vm is alive if necessary

    "qemu-img compare" is used to verify disk is mirrored successfully.
    """
    tag = params.get("source_image", "image1")
    qemu_img = qemu_storage.QemuImg(params, data_dir.get_data_dir(), tag)
    mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
    try:
        source_image = mirror_test.get_image_file()
        target_image = mirror_test.get_target_image()
        mirror_test.start()
        mirror_test.action_when_steady()
        mirror_test.vm.pause()
        mirror_test.reopen()
        mirror_test.action_after_reopen()
        device_id = mirror_test.vm.get_block({"file": target_image})
        if device_id != mirror_test.device:
            test.error("Mirrored image not being used by guest")
        error_context.context("Compare fully mirrored images", test.log.info)
        qemu_img.compare_images(source_image, target_image, force_share=True)
        mirror_test.vm.resume()
        if params.get("boot_target_image", "no") == "yes":
            mirror_test.vm.destroy()
            params = params.object_params(tag)
            if params.get("image_type") == "iscsi":
                params["image_raw_device"] = "yes"
            env_process.preprocess_vm(test, params, env, params["main_vm"])
            mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
        mirror_test.verify_alive()
    finally:
        mirror_test.clean()
