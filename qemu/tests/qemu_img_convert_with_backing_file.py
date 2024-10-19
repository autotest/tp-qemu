import json

from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Convert image with parameter -B -n
    1. Boot a guest with image1
    2. Create temporary file in the guest
    3. Get md5 value of the temporary file
    4. Destroy the guest
    5. Create a snapshot, base1 -> sn1
    6. Create a image and its snapshot, base2 -> sn2
    7. Convert base1 to base2 with parameter -n
    8. Convert sn1 to sn2 with parameter -B -n, set backing file to base2
    9. Boot sn2, check the md5 value of the temporary file
       Make sure the values are the same
    10. Destroy the guest
    11. Check sn1 is not allocated the entire image after the convert
    12. Check sn2 is not allocated the entire image after the convert
    13. Check the backing file of sn2, it should be base2
    14. remove base2, sn1 and sn2

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def prepare_images_from_params(image_chain, params):
        """Parse params to initialize a QImage."""
        params["image_chain"] = image_chain
        image_chain = params["image_chain"].split()
        base, sn = (
            qemu_storage.QemuImg(params.object_params(tag), root_dir, tag)
            for tag in image_chain
        )
        return base, sn

    def convert_images_from_params(convert_source, convert_target, backing_file=None):
        """Convert images with specified parameters"""
        source_params = convert_source.params
        target_params = convert_target.params
        skip_target_creation = target_params.get_boolean("skip_target_creation")
        cache_mode = params.get("cache_mode")
        source_cache_mode = params.get("source_cache_mode")
        source_params["convert_target"] = convert_target.tag
        source_params["convert_backing_file"] = backing_file
        test.log.info("Convert from %s to %s", convert_source.tag, convert_target.tag)
        fail_on((process.CmdError,))(convert_source.convert)(
            source_params, root_dir, cache_mode, source_cache_mode, skip_target_creation
        )

    def check_image_size(image):
        """Check image is not fully allocated"""
        test.log.info(
            "Verify qemu-img does not allocate the " "entire image after image convert"
        )
        info = json.loads(image.info(output="json"))
        virtual_size = info["virtual-size"]
        actual_size = info["actual-size"]
        if actual_size >= virtual_size:
            test.fail("qemu-img wrongly allocates to %s the entire image", image.tag)

    images = params["images"].split()
    params["image_name_%s" % images[0]] = params["image_name"]
    params["image_format_%s" % images[0]] = params["image_format"]
    vm = img_utils.boot_vm_with_images(test, params, env, (images[0],))
    session = vm.wait_for_login()
    guest_temp_file = params["guest_temp_file"]
    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")
    test.log.info("Create temporary file on guest: %s", guest_temp_file)
    img_utils.save_random_file_to_vm(vm, guest_temp_file, 2048 * 512, sync_bin)
    test.log.info("Get md5 value of the temporary file")
    md5_value = img_utils.check_md5sum(guest_temp_file, md5sum_bin, session)
    session.close()
    vm.destroy()

    root_dir = data_dir.get_data_dir()
    base1, sn1 = prepare_images_from_params(params["image_chain1"], params)
    test.log.info("Create snapshot %s", sn1.tag)
    sn1.create(sn1.params)
    base2, sn2 = prepare_images_from_params(params["image_chain2"], params)
    test.log.info("Create snapshot %s", sn2.tag)
    base2.create(base2.params)
    sn2.create(sn2.params)

    convert_images_from_params(base1, base2)
    convert_images_from_params(sn1, sn2, backing_file=base2.image_filename)

    vm = img_utils.boot_vm_with_images(test, params, env, (sn2.tag,))
    session = vm.wait_for_login()
    test.log.info("Verify md5 value of the temporary file")
    img_utils.check_md5sum(
        guest_temp_file, md5sum_bin, session, md5_value_to_check=md5_value
    )
    session.close()
    vm.destroy()

    check_image_size(sn1)
    check_image_size(sn2)

    test.log.info("Verify the snapshot chain of %s", sn2.tag)
    info = json.loads(sn2.info(output="json"))
    full_backing_filename = info["full-backing-filename"]
    if full_backing_filename != base2.image_filename:
        test.fail(
            "The full-backing-filename of %s is incorrect."
            "It should be %s, but it is %s.",
            sn2.tag,
            base2.image_filename,
            full_backing_filename,
        )
    base2.remove()
    sn1.remove()
    sn2.remove()
