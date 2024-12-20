from virttest.vt_imgr import vt_imgr


def run(test, params, env):
    images = dict()
    for image_tag in params.objects("images"):
        images[image_tag] = vt_imgr.query_image(image_tag)
        vt_imgr.backup_image(images[image_tag])
        test.log.info(
            "after backup: %s: %s", image_tag, vt_imgr.get_image_info(images[image_tag])
        )
        vt_imgr.restore_image(images[image_tag])
        test.log.info(
            "after restore: %s: %s",
            image_tag,
            vt_imgr.get_image_info(images[image_tag]),
        )

    for image_id in images.values():
        test.log.info("source: %s: %s", image_id, vt_imgr.get_image_info(image_id))
        cloned_image_id = vt_imgr.clone_image(image_id)
        test.log.info(
            "cloned: %s: %s", cloned_image_id, vt_imgr.get_image_info(cloned_image_id)
        )
        vt_imgr.update_image(cloned_image_id, {"destroy": {}})
        vt_imgr.destroy_image_object(cloned_image_id)
        vt_imgr.update_image(image_id, {"destroy": {}})
        vt_imgr.destroy_image_object(image_id)
