from virttest.vt_imgr import imgr


def run(test, params, env):
    images = dict()  # image tag: image object id

    test.log.info("Logical images defined in 'images' are taken care of by preprocess")
    for image_tag in params.objects("images"):
        images[image_tag] = imgr.query_logical_image(image_tag)
        test.log.info(
            "image tag:%s, image uuid: %s, image configuration: %s",
            image_tag,
            images[image_tag],
            imgr.get_logical_image_info(images[image_tag]),
        )

    test_image_tag = params["test_image_tag"]
    test.log.info("Now we create the logical image %s step by step", test_image_tag)
    images[test_image_tag] = imgr.create_logical_image_from_params(
        test_image_tag, params
    )
    imgr.update_logical_image(images[test_image_tag], "create")
    test.log.info(
        "image tag:%s, image uuid: %s, image configuration: %s",
        test_image_tag,
        images[test_image_tag],
        imgr.get_logical_image_info(images[test_image_tag]),
    )

    test.log.info("Now we backup the logical image %s", test_image_tag)
    imgr.update_logical_image(images[test_image_tag], "backup")
    test.log.info(
        "backup image tag:%s, image uuid: %s, image configuration: %s",
        test_image_tag,
        images[test_image_tag],
        imgr.get_logical_image_info(images[test_image_tag]),
    )

    test.log.info("Now we restore the logical image %s", test_image_tag)
    imgr.update_logical_image(images[test_image_tag], "restore")
    test.log.info(
        "restore image tag:%s, image uuid: %s, image configuration: %s",
        test_image_tag,
        images[test_image_tag],
        imgr.get_logical_image_info(images[test_image_tag]),
    )

    test.log.info("Now we clone the logical image %s", test_image_tag)
    cloned_image_id = imgr.clone_logical_image(images[test_image_tag])
    image_name = imgr.get_logical_image_info(cloned_image_id, request="meta.name")
    images[image_name] = cloned_image_id
    test.log.info(
        "clone image tag:%s, image uuid: %s, image configuration: %s",
        image_name,
        images[image_name],
        imgr.get_logical_image_info(images[image_name]),
    )

    test.log.info("Now we destroy the cloned image %s", image_name)
    imgr.update_logical_image(cloned_image_id, "destroy")
    test.log.info("Now we destroy the cloned image %s object", image_name)
    imgr.destroy_logical_image(cloned_image_id)
    images.pop(image_name)

    test.log.info("Now we destroy the test image %s", test_image_tag)
    imgr.update_logical_image(images[test_image_tag], "destroy")
    test.log.info("Now we destroy the cloned image %s object", test_image_tag)
    imgr.destroy_logical_image(images[test_image_tag])
    images.pop(test_image_tag)

    test.log.info("Images defined in 'images' will be cleaned by postprocess")
