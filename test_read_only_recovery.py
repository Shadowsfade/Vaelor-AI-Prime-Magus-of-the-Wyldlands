import json
from unittest.mock import patch
import pytest
from core import agent_loop
from core.tools.registry import ToolRegistry


def action():
    return json.dumps({'thought':'read', 'actions':[{'tool':'read_fixture','arguments':{}}], 'final':None})


@pytest.mark.parametrize('summary,expected', [
    ({'actions':[], 'final':{'status':'SUCCESS','summary':'marker-123'}}, 'SUCCESS'),
    ({'actions':[], 'final':{'status':'FAILED','summary':'missing evidence'}}, 'FAILED'),
    ({'actions':[{'tool':'read_fixture','arguments':{}}], 'final':{'status':'SUCCESS','summary':'guess'}}, 'FAILED'),
])
def test_read_only_stall_has_one_summary_without_extra_execution(summary, expected):
    registry=ToolRegistry()
    reads=[]
    registry.register('read_fixture','Read fixture',True,lambda: reads.append(1) or 'marker-123')
    replies=iter([action(),action(),action(),json.dumps(summary)])
    prompts=[]
    def model(prompt):
        prompts.append(prompt)
        return next(replies)
    with patch.object(agent_loop,'registry',registry),patch('core.tools.registry.register_all_tools'):
        result=agent_loop.run_agent('Read fixture',model,max_steps=3)
    assert result.startswith('FINAL_SUMMARY: '+expected)
    assert len(reads)==2
    assert len(prompts)==4
    assert 'marker-123' in prompts[-1]
    assert 'No further tools may be called' in prompts[-1]


def test_failed_reads_do_not_enter_summary_recovery():
    registry=ToolRegistry()
    registry.register('read_fixture','Read fixture',True,lambda: 'Refused: unavailable')
    replies=iter([action(),action(),action()])
    with patch.object(agent_loop,'registry',registry),patch('core.tools.registry.register_all_tools'):
        result=agent_loop.run_agent('Read fixture',lambda _:next(replies),max_steps=3)
    assert result.startswith('FINAL_SUMMARY: FAILED')


def test_cancellation_during_summary_prevents_success():
    registry=ToolRegistry()
    registry.register('read_fixture','Read fixture',True,lambda: 'marker-123')
    cancelled=False
    calls=0
    def model(prompt):
        nonlocal cancelled,calls
        calls+=1
        if calls==4:
            cancelled=True
            return json.dumps({'actions':[], 'final':{'status':'SUCCESS','summary':'marker-123'}})
        return action()
    with patch.object(agent_loop,'registry',registry),patch('core.tools.registry.register_all_tools'):
        result=agent_loop.run_agent('Read fixture',model,max_steps=3,should_cancel=lambda:cancelled)
    assert result.startswith('FINAL_SUMMARY: CANCELLED')


def test_mutating_runs_cannot_use_read_only_recovery():
    registry=ToolRegistry()
    executions=[]
    registry.register('read_fixture','Synthetic mutation',False,lambda: executions.append(1) or '[OK]')
    replies=iter([action(),action(),action()])
    events=[]
    with patch.object(agent_loop,'registry',registry),patch('core.tools.registry.register_all_tools'),patch.object(agent_loop,'_autonomy_mode',return_value='admin'):
        result=agent_loop.run_agent('Synthetic mutation',lambda _:next(replies),max_steps=3,event_callback=lambda e,d:events.append(e))
    assert result.startswith('FINAL_SUMMARY: FAILED')
    assert 'read_only_summary_started' not in events
    assert len(executions)==2
