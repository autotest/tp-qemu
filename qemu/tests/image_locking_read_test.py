from avocado import fail_on
from virttest import env_process, error_context, virt_vm

from qemu.tests.qemu_disk_img import QemuImgTest


@error_context.context_aware
def run(test, params, env):
    """
    Verification that image lock has no effect on the read operation from
    different image chain.
    Steps:
        1. create the first snapshot chain: image1 -> sn01 -> sn02
        2. boot first vm from sn02
        3. create the second snapshot chain: image1 -> sn11 -> sn12 ->sn13
        4. boot second vm frm sn13 and create a temporary file
        5. commit sn13
        6. boot second vm from sn12 and verify the temporary file is presented.
    """

    params.update(
        {
            "image_name_image1": params["image_name"],
            "image_format_image1": params["image_format"],
        }
    )

    error_context.context("boot first vm from first image chain", test.log.info)
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )
    vm1 = env.get_vm(params["main_vm"])
    vm1.verify_alive()

    params["images"] = params["image_chain"] = params["image_chain_second"]
    params["main_vm"] = params["vms"].split()[-1]
    sn_tags = params["image_chain"].split()[1:]
    images = [QemuImgTest(test, params, env, image) for image in sn_tags]

    error_context.context("create the second snapshot chain", test.log.info)
    for image in images:
        test.log.debug(
            "create snapshot %s based on %s",
            image.image_filename,
            image.base_image_filename,
        )
        image.create_snapshot()
        test.log.debug("boot from snapshot %s", image.image_filename)
        try:
            # ensure vm only boot with this snapshot
            image.start_vm({"boot_drive_%s" % image.tag: "yes"})
        except virt_vm.VMCreateError:
            # add images in second chain to images so they could be deleted
            # in postprocess
            params["images"] += " %s" % image
            test.fail("fail to start vm from snapshot %s" % image.image_filename)
        else:
            if image is not images[-1]:
                image.destroy_vm()

    tmpfile = params.get("guest_tmp_filename")
    error_context.context(
        "create a temporary file: %s in %s" % (tmpfile, image.image_filename),
        test.log.info,
    )
    hash_val = image.save_file(tmpfile)
    test.log.debug("The hash of temporary file:\n%s", hash_val)
    image.destroy_vm()

    error_context.context("commit image %s" % image.image_filename, test.log.info)
    fail_on()(image.commit)()

    error_context.context("check temporary file after commit", test.log.info)
    image = images[-2]
    test.log.debug("boot vm from %s", image.image_filename)
    image.start_vm({"boot_drive_%s" % image.tag: "yes"})
    if not image.check_file(tmpfile, hash_val):
        test.fail("File %s's hash is different after commit" % tmpfile)
