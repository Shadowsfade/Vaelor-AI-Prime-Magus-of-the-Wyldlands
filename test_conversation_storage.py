import multiprocessing
import os
from pathlib import Path
import pytest
from core.conversation_memory import VaelorConversationMemory
from core.storage_lock import StorageLock


def _write_turns(directory, prefix, start):
    start.wait(20)
    memory=VaelorConversationMemory(Path(directory), compact_after=10000)
    for number in range(20):
        memory.remember_turn(f'{prefix}-{number}', 'response', session_id='shared')


def _exit_holding_lock(path):
    with StorageLock(path):
        os._exit(0)


def test_concurrent_processes_preserve_every_turn(tmp_path):
    context=multiprocessing.get_context('spawn')
    start=context.Event()
    workers=[context.Process(target=_write_turns,args=(str(tmp_path),str(i),start)) for i in range(3)]
    try:
        for worker in workers:
            worker.start()
        start.set()
        for worker in workers:
            worker.join(35)
            assert worker.exitcode==0
        memory=VaelorConversationMemory(tmp_path)
        turns=memory.recall_recent(100,session_id='shared')
        assert len(turns)==60
        assert {turn['prompt'] for turn in turns}=={f'{i}-{n}' for i in range(3) for n in range(20)}
        assert len(memory.list_sessions())==1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)


def test_nested_objects_share_reentrant_storage_lock(tmp_path):
    first=VaelorConversationMemory(tmp_path)
    second=VaelorConversationMemory(tmp_path)
    with first._lock:
        second.remember_turn('question','answer',session_id='s')
    assert len(first.recall_recent(session_id='s'))==1


def test_process_exit_releases_storage_lock(tmp_path):
    path=tmp_path/'lock'
    process=multiprocessing.get_context('spawn').Process(target=_exit_holding_lock,args=(str(path),))
    process.start()
    process.join(15)
    assert process.exitcode==0
    with StorageLock(path,timeout=.5):
        pass


@pytest.mark.parametrize('raw',[b'not json',b'{}',b'\xff'])
def test_corrupt_history_is_preserved_and_not_overwritten(tmp_path,raw):
    memory=VaelorConversationMemory(tmp_path)
    memory.turns_path.write_bytes(raw)
    with pytest.raises(ValueError,match='damaged'):
        memory.remember_turn('new','reply',session_id='s')
    assert memory.turns_path.read_bytes()==raw
    backups=list(tmp_path.glob('conversations.json.corrupt-*'))
    assert len(backups)==1
    assert backups[0].read_bytes()==raw
