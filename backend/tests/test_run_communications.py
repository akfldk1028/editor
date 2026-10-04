import pytest
from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError


def run(**extra):
    return {'run_id':'r','owner_project_id':'p','branch_id':'main','request_id':'editor:b:k',
        'goal':'health','status':'succeeded','receipt_task_ids':['health'],'pending_input':False,**extra}


def message(**extra):
    return {'id':'health','task_id':'health','tool':'health','agent':'law','state':'finished',
        'request_text':'{}','response_text':'{"status":"ok"}','transport':'a2a','truncated':False,**extra}


def test_saved_communications_survive_product_adapter():
    value=OrchestratorClient.parse_run(run(communications=[message()],communications_available=True,communications_truncated=False))
    assert value['communications']==[message()]
    assert value['communications_available'] is True


@pytest.mark.parametrize('changes',[{'response_text':{}},{'transport':'invented'},{'truncated':'false'},{'request_text':'x'*8001}])
def test_invalid_communications_are_not_presented_as_empty_success(changes):
    with pytest.raises(OwnerContractError):
        OrchestratorClient.parse_run(run(communications=[message(**changes)],communications_available=True,communications_truncated=False))


def test_old_gateway_is_explicitly_unavailable():
    value=OrchestratorClient.parse_run(run())
    assert value['communications_available'] is False
    assert value['communications']==[]
