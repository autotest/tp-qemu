import re

from avocado.utils import process
from virttest import data_dir, error_context
from virttest.qemu_storage import QemuImg


@error_context.context_aware
def run(test, params, env):
    """
    Run qcow2 performance tests:
    1. Create image with given parameters
    2. Write to the image to prepare a certain size image
    3. Do one operations to the image and measure the time
    4. Record the results

    :param test:   QEMU test object
    :param params: Dictionary with the test parameters
    :param env:    Dictionary with test environment.
    """
    image_chain = params.get("image_chain")
    test_image = int(params.get("test_image", "0"))
    interval_size = params.get("interval_szie", "64k")
    write_round = int(params.get("write_round", "16384"))
    op_type = params.get("op_type")
    new_base = params.get("new_base")
    writecmd = params.get("writecmd")
    iocmd = params.get("iocmd")
    opcmd = params.get("opcmd")
    io_options = params.get("io_options", "n")
    cache_mode = params.get("cache_mode")
    image_dir = data_dir.get_data_dir()

    if not re.match(r"\d+", interval_size[-1]):
        write_unit = interval_size[-1]
        interval_size = int(interval_size[:-1])
    else:
        interval_size = int(interval_size)
        write_unit = ""

    error_context.context("Init images for testing", test.log.info)
    sn_list = []
    for img in re.split(r"\s+", image_chain.strip()):
        image_params = params.object_params(img)
        sn_tmp = QemuImg(image_params, image_dir, img)
        sn_tmp.create(image_params)
        sn_list.append((sn_tmp, image_params))

    # Write to the test image
    error_context.context(
        "Prepare the image with write a certain size block", test.log.info
    )
    dropcache = "echo 3 > /proc/sys/vm/drop_caches && sleep 5"
    snapshot_file = sn_list[test_image][0].image_filename

    if op_type != "writeoffset1":
        offset = 0
        writecmd0 = writecmd % (
            write_round,
            offset,
            interval_size,
            write_unit,
            interval_size,
            write_unit,
        )
        iocmd0 = iocmd % (writecmd0, io_options, snapshot_file)
        test.log.info("writecmd-offset-0: %s", writecmd0)
        process.run(dropcache, shell=True)
        output = process.run(iocmd0, shell=True)
    else:
        offset = 1
        writecmd1 = writecmd % (
            write_round,
            offset,
            interval_size,
            write_unit,
            interval_size,
            write_unit,
        )
        iocmd1 = iocmd % (writecmd1, io_options, snapshot_file)
        test.log.info("writecmd-offset-1: %s", writecmd1)
        process.run(dropcache, shell=True)
        output = process.run(iocmd1, shell=True)

    error_context.context(
        "Do one operations to the image and " "measure the time", test.log.info
    )

    if op_type == "read":
        readcmd = opcmd % (io_options, snapshot_file)
        test.log.info("read: %s", readcmd)
        process.run(dropcache, shell=True)
        output = process.run(readcmd, shell=True)
    elif op_type == "commit":
        commitcmd = opcmd % (cache_mode, snapshot_file)
        test.log.info("commit: %s", commitcmd)
        process.run(dropcache, shell=True)
        output = process.run(commitcmd, shell=True)
    elif op_type == "rebase":
        new_base_img = QemuImg(params.object_params(new_base), image_dir, new_base)
        new_base_img.create(params.object_params(new_base))
        rebasecmd = opcmd % (new_base_img.image_filename, cache_mode, snapshot_file)
        test.log.info("rebase: %s", rebasecmd)
        process.run(dropcache, shell=True)
        output = process.run(rebasecmd, shell=True)
    elif op_type == "convert":
        convertname = sn_list[test_image][0].image_filename + "_convert"
        convertcmd = opcmd % (snapshot_file, cache_mode, convertname)
        test.log.info("convert: %s", convertcmd)
        process.run(dropcache, shell=True)
        output = process.run(convertcmd, shell=True)

    error_context.context("Result recording", test.log.info)
    result_file = open(
        "%s/%s_%s_results" % (test.resultsdir, "qcow2perf", op_type), "w"
    )
    result_file.write("%s:%s\n" % (op_type, output))
    test.log.info("%s takes %s", op_type, output)
    result_file.close()
