from backend.tests.test_native_design_api import api
from backend.app.modules.design.execution import ExecutionService
from backend.app.modules.design.worker import run_once


def test_http_create_queue_worker_replay_and_result(api,tmp_path):
    client,url,_,payload,_=api
    payload['job_spec']['options'].update({'Number of generations':2,'num_islands':2,'pop_per_island':8,'tournament_size':4})
    job=client.post(url,json={'request_id':'spec','scene_revision':2,'payload':payload}).json()
    path=url+'/'+job['job_id']+'/attempts'
    body={'request_id':'run','scene_revision':2,'seed':42,'unverified_search':True}
    response=client.post(path,json=body)
    assert response.status_code==202,response.text
    attempt=response.json()
    assert attempt['status']=='queued'
    assert client.post(path,json=body).json()==attempt
    assert client.get(path).json()['items']==[attempt]
    assert client.get(path+'/'+attempt['attempt_id']+'/result').json() is None
    assert run_once(ExecutionService(tmp_path/'design'))
    assert client.get(path+'/'+attempt['attempt_id']).json()['status']=='computed'
    assert client.get(path+'/'+attempt['attempt_id']+'/result').json()['total_evaluated']==20
    events=client.get(path+'/'+attempt['attempt_id']+'/events').json()['items']
    assert events[-1]['type']=='computed'
    assert client.get(path+'/'+attempt['attempt_id']+'/events?after='+str(events[-1]['sequence'])).json()['items']==[]
    assert client.get(url+'/'+job['job_id']).json()==job


def test_execution_api_live_guards_and_cancel(api):
    client,url,sources,payload,foreign=api
    job=client.post(url,json={'request_id':'spec','scene_revision':2,'payload':payload}).json()
    path=url+'/'+job['job_id']+'/attempts'
    body={'request_id':'run','scene_revision':2,'seed':42,'unverified_search':True}
    assert client.post(path,json=body,headers={'origin':'https://other.invalid'}).status_code==403
    assert client.post(path,json={**body,'seed':True}).status_code==422
    assert client.post(path,json={**body,'unverified_search':False}).status_code==422
    sources.version=3
    assert client.post(path,json=body).status_code==409
    sources.version=2
    attempt=client.post(path,json=body).json()
    assert client.post(path+'/'+attempt['attempt_id']+'/cancel',json={'scene_revision':2}).json()['status']=='cancelled'
    assert client.get(f'/api/v1/platform/projects/{foreign}/design/native-jobs/{job["job_id"]}/attempts/{attempt["attempt_id"]}').status_code==404
