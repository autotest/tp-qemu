import logging
import time

from avocado import fail_on
from virttest import utils_misc

LOG_JOB = logging.getLogger("avocado.test")

BLOCK_JOB_COMPLETED_EVENT = "BLOCK_JOB_COMPLETED"
BLOCK_JOB_CANCELLED_EVENT = "BLOCK_JOB_CANCELLED"
BLOCK_JOB_ERROR_EVENT = "BLOCK_JOB_ERROR"
BLOCK_IO_ERROR_EVENT = "BLOCK_IO_ERROR"


def get_job_status(vm, device):
    """
    Get block job state

    :param vm: VM object
    :param device: device ID or node-name

    return str: block job state string
    """
    job = get_job_by_id(vm, device)
    return job.get("status")


@fail_on
def wait_until_job_status_match(vm, status, device, timeout):
    """
    Block until job state match to expect state

    :param vm: VM object
    :param status: expect state string
    :param device: device ID or node-name
    :param timeout: blocked timeout
    """
    matched = utils_misc.wait_for(
        lambda: get_job_status(vm, device) == status, timeout=timeout
    )
    assert matched, "wait job status to '%s' timeout in %s seconds" % (status, timeout)


@fail_on
def wait_until_block_job_completed(vm, job_id, timeout=900):
    """Block until block job completed"""

    def _wait_until_block_job_completed():
        finished = False
        status = get_job_status(vm, job_id)
        if status == "pending":
            block_job_finalize(vm, job_id)
        if status == "ready":
            try:
                arguments = {"id": job_id}
                vm.monitor.cmd("job-complete", arguments)
            except Exception as err:
                LOG_JOB.debug("'job-complete' hit error: %s", err.data["desc"])
        try:
            for event in vm.monitor.get_events():
                if event.get("event") != BLOCK_JOB_COMPLETED_EVENT:
                    continue
                data = event.get("data", dict())
                if job_id in [data.get("id"), data.get("device")]:
                    error = data.get("error")
                    assert not error, "block backup job finished with error: %s" % error
                    finished = True
                    break
        finally:
            status = get_job_status(vm, job_id)
            if status == "concluded":
                block_job_dismiss(vm, job_id)
        return finished

    finished = utils_misc.wait_for(
        _wait_until_block_job_completed, first=0.1, timeout=timeout
    )
    assert finished, "wait for block job complete event timeout in %s seconds" % timeout


@fail_on
def job_complete(vm, job_id, timeout=120):
    wait_until_job_status_match(vm, "ready", job_id, timeout)
    arguments = {"id": job_id}
    vm.monitor.cmd("job-complete", arguments)


@fail_on
def block_job_complete(vm, job_id, timeout=120):
    job_complete(vm, job_id, timeout)


@fail_on
def block_job_dismiss(vm, job_id, timeout=120):
    """
    Dismiss block job when job in concluded state
    """
    job = get_block_job_by_id(vm, job_id)
    if job.get("auto-dismiss", True) is False:
        _job_dismiss(vm, job_id, timeout)
        time.sleep(0.1)
        job = get_block_job_by_id(vm, job_id)
        assert not job, "Block job '%s' exists" % job_id


@fail_on
def job_dismiss(vm, job_id, timeout=120):
    """dismiss job when job status is concluded"""
    _job_dismiss(vm, job_id, timeout)
    time.sleep(0.1)
    job = get_job_by_id(vm, job_id)
    assert not job, "Job '%s' exists" % job_id


def _job_dismiss(vm, job_id, timeout=120):
    """dismiss job when job status is concluded"""
    wait_until_job_status_match(vm, "concluded", job_id, timeout)
    arguments = {"id": job_id}
    return vm.monitor.cmd("job-dismiss", arguments)


def block_job_finalize(vm, job_id, timeout=120):
    """Finalize block job when job in pending state"""
    job = get_block_job_by_id(vm, job_id)
    if job.get("auto-finalize", True) is False:
        return _job_finalize(vm, job_id, timeout)


def job_finalize(vm, job_id, timeout=120):
    """Finalize job when job in pending state"""
    return _job_finalize(vm, job_id, timeout)


@fail_on
def _job_finalize(vm, job_id, is_block_job=False, timeout=120):
    """Finalize job when job in pending state"""
    wait_until_job_status_match(vm, "pending", job_id, timeout)
    arguments = {"id": job_id}
    vm.monitor.cmd("job-finalize", arguments)


@fail_on
def get_job_by_id(vm, job_id):
    """Get block job info by job ID"""
    for job in query_jobs(vm):
        if job["id"] == job_id:
            return job
    return dict()


@fail_on
def get_block_job_by_id(vm, job_id):
    for job in query_block_jobs(vm):
        if job["device"] == job_id:
            return job
    return dict()


def query_jobs(vm):
    """Get block jobs info list in given VM"""
    return vm.monitor.cmd("query-jobs")


def query_block_jobs(vm):
    """Get jobs info list in given VM"""
    return vm.monitor.cmd("query-block-jobs")


def make_transaction_action(cmd, data):
    """
    Make transaction action dict by arguments
    """
    prefix = "x-"
    if not cmd.startswith(prefix):
        for k in data.keys():
            if data.get(k) is None:
                data.pop(k)
                continue
            if cmd == "block-dirty-bitmap-add" and k == "x-disabled":
                continue
            if k.startswith(prefix):
                data[k.lstrip(prefix)] = data.pop(k)
    return {"type": cmd, "data": data}


@fail_on
def get_event_by_condition(vm, event_name, tmo=30, **condition):
    """
    Get event by the event name and other conditions in some time

    :param vm: VM object
    :param event_name: event name
    :param tmo: getting job event timeout
    :param condition: id or device or node-name

    :return: The event dict or None
    """
    event = None
    for i in range(tmo):
        all_events = vm.monitor.get_events()
        events = [e for e in all_events if e.get("event") == event_name]
        if condition:
            events = [
                e
                for e in events
                if e.get("data")
                and all(item in e["data"].items() for item in condition.items())
            ]
        if events:
            event = events[0]
            break
        time.sleep(1)
    return event


def is_block_job_started(vm, jobid, tmo=10):
    """
    offset should be greater than 0 when block job starts,
    return True if offset > 0 in tmo, or return False
    """
    for i in range(tmo):
        job = get_block_job_by_id(vm, jobid)
        if not job:
            LOG_JOB.debug("job %s was not found", jobid)
            break
        elif job["offset"] > 0:
            return True
        time.sleep(1)
    else:
        LOG_JOB.debug("block job %s never starts in %s", jobid, tmo)
    return False


def check_block_jobs_started(vm, jobid_list, tmo=10):
    """
    Test failed if any block job failed to start
    """
    started = all(list(map(lambda j: is_block_job_started(vm, j, tmo), jobid_list)))
    assert started, "Not all block jobs start successfully"


def is_block_job_running(vm, jobid, tmo=200):
    """
    offset should keep increasing when block job keeps running,
    return True if offset increases in tmo, or return False
    """
    offset = None
    for i in range(tmo):
        job = get_block_job_by_id(vm, jobid)
        if not job:
            LOG_JOB.debug("job %s cancelled unexpectedly", jobid)
            break
        elif job["status"] not in ["running", "pending", "ready"]:
            LOG_JOB.debug("job %s is not in running status", jobid)
            return False
        elif offset is None:
            if job["status"] in ["pending", "ready"]:
                return True
            else:
                offset = job["offset"]
        elif job["offset"] > offset:
            return True
        time.sleep(1)
    else:
        LOG_JOB.debug("offset never changed for block job %s in %s", jobid, tmo)
    return False


def check_block_jobs_running(vm, jobid_list, tmo=200):
    """
    Test failed if any block job's offset never increased
    """
    running = all(list(map(lambda j: is_block_job_running(vm, j, tmo), jobid_list)))
    assert running, "Not all block jobs are running"


def is_block_job_paused(vm, jobid, tmo=50):
    """
    offset should stay the same when block job paused,
    return True if offset never changed in tmo, or return False
    """
    offset = None
    time.sleep(10)

    for i in range(tmo):
        job = get_block_job_by_id(vm, jobid)
        if not job:
            LOG_JOB.debug("job %s cancelled unexpectedly", jobid)
            return False
        elif job["status"] != "running":
            LOG_JOB.debug("job %s is not in running status", jobid)
            return False
        elif offset is None:
            offset = job["offset"]
        elif offset != job["offset"]:
            LOG_JOB.debug("offset %s changed for job %s in %s", offset, jobid, tmo)
            return False
        time.sleep(1)
    return True


def check_block_jobs_paused(vm, jobid_list, tmo=50):
    """
    Test failed if any block job's offset changed
    """
    paused = all(list(map(lambda j: is_block_job_paused(vm, j, tmo), jobid_list)))
    assert paused, "Not all block jobs are paused"
