import json
import logging

from collections import namedtuple

from qemu.tests.qemu_disk_img import QemuImgTest


def run(test, params, env):
    """
    Commit with explicit backing file specification.

    1. create snapshot chain as image1->sn1->sn2
    2. commit sn2 to base
    3. check to see that sn2 is not emptied and the temp file in corresponding
    snapshot remains intact.
    """

    def prepare_images_from_params(images, params):
        """Parse params to initialize a QImage list."""
        return [QImage(tag, QemuImgTest(test, params, env, tag))
                for tag in images]

    def verify_backing_chain(info):
        """Verify image's backing chain."""
        for image, img_info in zip(images, reversed(info)):
            base_image = getattr(image.imgobj, "base_image_filename", None)
            base_image_from_info = img_info.get("full-backing-filename")
            if base_image != base_image_from_info:
                test.fail(("backing chain check for image %s failed, backing"
                           " file from info is %s, which should be %s.") %
                          (image.imgobj.image_filename, base_image_from_info,
                           base_image))

    QImage = namedtuple("QImage", ["tag", "imgobj"])
    images = params.get("image_chain", "").split()
    if len(images) < 3:
        test.cancel("Snapshot chain must at least contains three images")
    params["image_name_%s" % images[0]] = params["image_name"]
    params["image_format_%s" % images[0]] = params["image_format"]
    images = prepare_images_from_params(images, params)
    base, active_layer = images[0], images[-1]

    hashes = {}
    for image in images:
        if image is not base:
            logging.debug("Create snapshot %s based on %s",
                          image.imgobj.image_filename,
                          image.imgobj.base_image_filename)
            image.imgobj.create_snapshot()
        image.imgobj.start_vm()
        guest_file = params["guest_tmp_filename"] % image.tag
        logging.debug("Create tmp file %s in image %s", guest_file,
                      image.imgobj.image_filename)
        hashes[guest_file] = image.imgobj.save_file(guest_file)
        image.imgobj.destroy_vm()

    logging.debug("Hashes of temporary files:\n%s", hashes)

    logging.debug("Verify the snapshot chain")
    info = json.loads(active_layer.imgobj.info(output="json"))
    active_layer_size_before = info[0]["actual-size"]
    verify_backing_chain(info)

    logging.debug("Commit image")
    active_layer.imgobj.commit(base=base.tag)

    logging.debug("Verify the snapshot chain after commit")
    info = json.loads(active_layer.imgobj.info(output="json"))
    active_layer_size_after = info[0]["actual-size"]
    logging.debug("%s file size before commit: %s, after commit: %s",
                  active_layer.imgobj.image_filename, active_layer_size_before,
                  active_layer_size_after)
    if active_layer_size_after < active_layer_size_before:
        test.fail("image %s is emptied after commit with explicit base" %
                  active_layer.imgobj.image_filename)
    verify_backing_chain(info)

    logging.debug("Verify hashes of temporary files")
    base.imgobj.start_vm()
    for tmpfile, hashval in hashes.items():
        if not base.imgobj.check_file(tmpfile, hashval):
            test.fail("File %s's hash is different after commit" % tmpfile)

    for image in images:
        image.imgobj.clean()
