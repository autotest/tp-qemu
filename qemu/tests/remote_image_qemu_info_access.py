from virttest import error_context, qemu_storage


@error_context.context_aware
def run(test, params, env):
    """
    1) Access remote image by qemu-img info
    2) Check url in output for libcurl backend
    3) Replace '_' with '%5f' in image name,
       access image
    4) Check url in output for libcurl backend

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    img_params = params.object_params(params["remote_image_tag"])
    image_name_list = [
        img_params["curl_path"],
        img_params["curl_path"].replace(
            params["replace_symbol"], params["ascii_symbol"]
        ),
    ]

    for image_name in image_name_list:
        img_params["curl_path"] = image_name
        img_obj = qemu_storage.QemuImg(img_params, None, params["remote_image_tag"])

        test.log.info("Access image: %s", img_obj.image_filename)
        out = img_obj.info()

        if img_obj.image_filename not in out:
            test.fail(
                "Failed to get url(%s) from output(%s)" % (img_obj.image_filename, out)
            )
