import os
import glob
import shutil
import logging

from autotest.client import os_dep
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest import data_dir
from virttest import utils_misc

corefilemap = {"linux": "/var/crash",
               "windows": "win:c:\windows\dump"}


def thrice_run_cmd(cmd, ignore_status=True):
    count = 1
    while count < 4:
        results = utils.run(cmd, ignore_status=ignore_status)
        if results.exit_status == 0:
            return results
        count += 1
    return results


def get_ostype(filename, resultsdir):
    """
    Get guest OS type via image file
    """
    logging.info("Inspect os of image file: %s" % filename)
    cmdprefix = "guestfish -i --ro -a %s " % filename
    inspectoscmd = "%s inspect-os" % cmdprefix
    results = thrice_run_cmd(inspectoscmd, ignore_status=True)
    if results.exit_status != 0:
        logging.debug("inspect os root with error: %s" % results.stderr)
        return None
    inspecttypecmd = "%s inspect-get-type %s" % (cmdprefix, results.stdout)
    results = thrice_run_cmd(inspecttypecmd, ignore_status=True)
    if results.exit_status != 0:
        logging.debug("inspect os type with error: %s" % results.stderr)
        return None
    return results.stdout.strip()


def get_images(imagesdir, resultsdir):
    """
    Get image file path from image data dir, skip no OS images
    """
    for root, dirs, files in os.walk(imagesdir):
        for file in files:
            path = os.path.join(root, file)
            ostype = get_ostype(path, resultsdir)
            if ostype not in corefilemap.keys():
                continue
            yield path


def get_dumpfiles(filename, resultsdir):
    """
    Copy out coredump file from guest image to host autotest
    result data dir.
    """
    basename = os.path.basename(filename)
    ostype = get_ostype(filename, resultsdir)
    srcdir = corefilemap[ostype]
    dstdir = os.path.join(resultsdir, basename)
    copycmd = ("guestfish -i --ro -a %s copy-out %s %s" %
               (filename, srcdir, dstdir))
    results = thrice_run_cmd(copycmd, ignore_status=True)
    if results.exit_status == 0:
        dumpfiles = glob.glob("%s/*" % dstdir)
        if dumpfiles:
            return dumpfiles
        shutil.rmtree(dstdir)
    return []


def get_corefiles(resultsdir):
    """
    Recursive scan results dir to find core file
    """
    for root, dirs, files in os.walk(resultsdir):
        for cfile in files:
            if cfile == "core":
                filename = os.path.join(root, cfile)
                yield filename
        for sdir in dirs:
            sdir = os.path.join(root, sdir)
            get_corefiles(sdir)


def scan_images_dir(imagesdir, resultsdir):
    """
    Scan image files under image dir and mount image to look
    kernel dump files in each image.
    """
    dumpinfos = []
    os_dep.command("guestfish")
    for image in get_images(imagesdir, resultsdir):
        dumpfiles = get_dumpfiles(image, resultsdir)
        if dumpfiles:
            dumpinfos.append((image, dumpfiles))
    return dumpinfos


def scan_results_dir(resultsdir):
    """
    Scan each test results directory to find coredump file
    """
    coreinfos = []
    for corefile in get_corefiles(resultsdir):
        dirname = os.path.dirname(os.path.dirname(corefile))
        shortname = os.path.basename(dirname)
        corefile = os.path.basename(corefile)
        coreinfos.append((shortname, corefile))
    return coreinfos


@error.context_aware
def run(test, params, env):
    """
    Post test, this case will scan results directory to detect
    core dump file. And check each image file under image
    directory to obtain guest kernel dumps. In the end, will go
    through host dmesg log to report host error.
    """
    infos = ""
    error.context("Scan results dirs to find core file", logging.info)
    resultsdir = "/".join(test.resultsdir.split('/')[:-2])
    coreinfos = [(shortname, corefiles) for shortname, corefiles in
                 scan_results_dir(resultsdir)]
    error.context("Scan image files to obtain guest dumpfile", logging.info)
    imagesdir = os.path.join(data_dir.get_data_dir(), "images")
    dumpinfos = [(imagefile, dumpfile) for imagefile, dumpfile in
                 scan_images_dir(imagesdir, test.resultsdir)]
    error.context("Check host dmesg", logging.info)
    try:
        utils_misc.verify_host_dmesg()
    except Exception, details:
        infos += "\n%s" % details.message
    if coreinfos:
        infos += "\nTotally %d core files found, details:" % len(coreinfos)
        for casename, corefiles in coreinfos:
            infos += ("\n%s%d core files found in test %s" %
                      (len(corefiles), casename))
    if dumpinfos:
        infos += "\nTotally %d dump file found, details:" % len(dumpinfos)
        for imagefile, dumpfiles in dumpinfos:
            infos += ("\n%d dump files found in image file %s" %
                      (len(dumpfiles), imagefile))
    if infos:
        raise error.TestFail(infos)
