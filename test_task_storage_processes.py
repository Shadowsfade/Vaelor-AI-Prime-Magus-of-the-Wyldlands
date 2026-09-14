import multiprocessing
from pathlib import Path
import pytest
from core.task_store import TaskStore


def worker(path,start,results,operation,task_id,owner):
    store=TaskStore(Path(path))
    start.wait(20)
    if operation=='claim':
        result=bool(store.claim(task_id,owner))
    elif operation=='approve':
        result=store.consume_action_approval(task_id,'fingerprint')
    else:
        for number in range(15):
            store.create(f'{owner}-{number}')
        result=True
    results.put(result)


def race(tmp_path,operation,task_id=None):
    context=multiprocessing.get_context('spawn')
    start=context.Event();results=context.Queue()
    workers=[context.Process(target=worker,args=(str(tmp_path/'tasks.json'),start,results,operation,task_id,str(i))) for i in range(3)]
    try:
        for process in workers: process.start()
        start.set()
        values=[results.get(timeout=35) for _ in workers]
        for process in workers:
            process.join(10)
            assert process.exitcode==0
        return values
    finally:
        for process in workers:
            if process.is_alive():
                process.terminate();process.join(5)
        results.close()
        results.join_thread()


def test_only_one_process_claims_task(tmp_path):
    store=TaskStore(tmp_path/'tasks.json')
    task=store.create('inspect')
    assert sum(race(tmp_path,'claim',task['id']))==1
    assert store.get(task['id'])['status']=='running'


def test_approval_is_consumed_by_only_one_process(tmp_path):
    store=TaskStore(tmp_path/'tasks.json')
    task=store.create('approved test')
    store.request_approval(task['id'],{'fingerprint':'fingerprint'})
    store.approve_action(task['id'],'fingerprint')
    assert sum(race(tmp_path,'approve',task['id']))==1


def test_concurrent_task_creation_loses_no_records(tmp_path):
    assert all(race(tmp_path,'create'))
    assert len(TaskStore(tmp_path/'tasks.json').list(100))==45


@pytest.mark.parametrize('raw',[b'broken',b'{}',b'[null]',b'\xff'])
def test_corrupt_task_state_is_preserved(tmp_path,raw):
    path=tmp_path/'tasks.json';path.write_bytes(raw)
    with pytest.raises(ValueError,match='damaged'):
        TaskStore(path)
    assert path.read_bytes()==raw
    backups=list(tmp_path.glob('tasks.json.corrupt-*'))
    assert len(backups)==1 and backups[0].read_bytes()==raw


def test_opening_store_preserves_live_worker_lease(tmp_path):
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("active work")
    claimed = store.claim(task["id"], "live-worker")
    reopened = TaskStore(store.path).get(task["id"])
    assert reopened["status"] == "running"
    assert reopened["lease"] == claimed["lease"]


def test_supervisor_recovers_lease_that_expires_after_startup(tmp_path):
    from datetime import datetime, timedelta, timezone
    from core.supervisor import SupervisorRunner
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("unfinished mutation")
    now = datetime.now(timezone.utc)
    store.claim(task["id"], "worker", lease_seconds=60, now=now)
    store.begin_step(task["id"], "worker", "shell", "mutation")
    runner = SupervisorRunner(store, owner="replacement")
    assert runner.eligible(now) == []
    eligible = runner.eligible(now + timedelta(seconds=61))
    assert len(eligible) == 1
    assert eligible[0]["recovery"]["decision"] == "VERIFY_BEFORE_RETRY"
    assert eligible[0]["lease"] is None
