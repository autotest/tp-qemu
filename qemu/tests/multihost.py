from virttest.vt_imgr import imgr


def run(test, params, env):
    images = dict()
    for image_tag in params.objects("images"):
        images[image_tag] = imgr.query_virt_image(image_tag)
        imgr.update_virt_image(images[image_tag], {"backup": {}})
        test.log.info(
            "after backup: %s: %s",
            image_tag,
            imgr.get_virt_image_info(images[image_tag]),
        )
        imgr.update_virt_image(images[image_tag], {"restore": {}})
        test.log.info(
            "after restore: %s: %s",
            image_tag,
            imgr.get_virt_image_info(images[image_tag]),
        )

    for image_id in images.values():
        test.log.info("source: %s: %s", image_id, imgr.get_virt_image_info(image_id))
        cloned_image_id = imgr.clone_virt_image(image_id)
        test.log.info(
            "cloned: %s: %s", cloned_image_id, imgr.get_virt_image_info(cloned_image_id)
        )
        imgr.update_virt_image(cloned_image_id, {"destroy": {}})
        imgr.destroy_virt_image_object(cloned_image_id)
        imgr.update_virt_image(image_id, {"destroy": {}})
        imgr.destroy_virt_image_object(image_id)
