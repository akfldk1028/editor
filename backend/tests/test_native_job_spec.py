from copy import deepcopy
import json
from pathlib import Path

import pytest
from shapely.geometry import box, mapping

from backend.app.modules.land.projection import utm_to_wgs84
from backend.app.modules.design.job_spec import prepare_job, JobSpecError

FIXTURE = json.loads((Path(__file__).parent/'fixtures/native_job_specs.json').read_text(encoding='utf-8'))


def site(width=30, depth=30):
    return json.loads(json.dumps(mapping(utm_to_wgs84(box(300000,4100000,300000+width,4100000+depth)))))


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case:case['algorithm']+'-'+case['building_type'])
def test_complete_default_spec_matches_original_source(case):
    options={key:case[key] for key in ('algorithm','building_type')}
    result=prepare_job({'site_polygon':site(),'constraints':FIXTURE['constraints'],'job_spec':{'options':options}})
    expected=deepcopy(case['expected']);expected['options'].update(options)
    assert result['job_spec']==expected
    assert result['site_area_m2']==900.0
    assert result['population_size']==210 and result['max_generations']==120


@pytest.mark.parametrize('options', [{'algorithm':'typo'},{'Number of generations':True},{'Number of generations':100001},{'unknown':1},{'initial_mutation_rate':float('nan')}])
def test_invalid_options_fail_explicitly(options):
    with pytest.raises(JobSpecError):prepare_job({'site_polygon':site(),'job_spec':{'options':options}})


def test_holes_original_inputs_and_supplied_options_are_retained():
    geometry=site();geometry['coordinates'].append(site(5,5)['coordinates'][0])
    # Put the hole strictly inside the exterior.
    geometry['coordinates'][1]=json.loads(json.dumps(mapping(utm_to_wgs84(box(300010,4100010,300015,4100015)))))['coordinates'][0]
    payload={'site_polygon':geometry,'job_spec':{'options':{'penalty_mode':'binary','island_mode':'heterogeneous'}}}
    before=deepcopy(payload);result=prepare_job(payload)
    assert payload==before and result['site_polygon']==geometry
    assert result['site_area_m2']==875.0
    assert result['job_spec']['options']['penalty_mode']=='binary'


@pytest.mark.parametrize('geometry',[site(2,30),site(3,3),{'type':'MultiPolygon','coordinates':[site()['coordinates']]}, {'type':'Polygon','coordinates':[[[True,37],[127,37],[127,38],[True,37]]]}])
def test_invalid_site_boundaries_are_rejected(geometry):
    with pytest.raises(JobSpecError):prepare_job({'site_polygon':geometry})


def test_complete_spec_constraint_merge_preserves_metric_roles():
    original=prepare_job({'site_polygon':site()})['job_spec']
    original['options']['Number of generations']=2
    constraint={'name':'floor_area','type':'Constraint','Requirement':'Less than','val':1000}
    result=prepare_job({'site_polygon':site(),'job_spec':original,'constraints':[constraint]})
    assert result['job_spec']['outputs'][-1]==constraint
    assert result['max_generations']==2


@pytest.mark.parametrize('mutation', ['duplicate','unknown_metric','invalid_range','wrong_gene','empty_outputs'])
def test_complete_spec_rejects_ambiguous_or_unmeasured_definitions(mutation):
    spec=prepare_job({'site_polygon':site()})['job_spec']
    if mutation=='duplicate':spec['outputs'].append(deepcopy(spec['outputs'][0]))
    if mutation=='unknown_metric':spec['outputs'][0]['name']='not_measured'
    if mutation=='invalid_range':spec['inputs'][0]['Min']=spec['inputs'][0]['Max']+1
    if mutation=='wrong_gene':spec['inputs'][0]['name']='unknown_gene'
    if mutation=='empty_outputs':spec['outputs']=[]
    with pytest.raises(JobSpecError):prepare_job({'site_polygon':site(),'job_spec':spec})


def test_returned_spec_cannot_mutate_later_job_defaults():
    first=prepare_job({'site_polygon':site()})
    first['job_spec']['outputs'][0]['name']='corrupt'
    assert prepare_job({'site_polygon':site()})['job_spec']['outputs'][0]['name']=='floor_area'


@pytest.mark.parametrize('record', [
    {'name':[],'type':'Constraint','Requirement':'Less than','val':1},
    {'name':'bcr','type':'Constraint','Requirement':'Less than','val':True},
    {'name':'bcr','type':'Constraint','Requirement':'Approximate','val':50},
])
def test_malformed_constraints_raise_typed_error(record):
    with pytest.raises(JobSpecError) as error:
        prepare_job({'site_polygon':site(),'constraints':[record]})
    assert error.value.code and error.value.message


def test_complete_spec_does_not_erase_conflicting_requested_constraint():
    constraint={'name':'bcr','type':'Constraint','Requirement':'Less than','val':50}
    spec=prepare_job({'site_polygon':site(),'constraints':[constraint]})['job_spec']
    with pytest.raises(JobSpecError,match='conflicts'):
        prepare_job({'site_polygon':site(),'job_spec':spec,'constraints':[{**constraint,'val':60}]})


def test_small_valid_site_with_reversed_default_gene_ranges_is_explicitly_rejected():
    with pytest.raises(JobSpecError) as error:
        prepare_job({'site_polygon':site(4,4)})
    assert error.value.code=='invalid_gene_range'


def test_complete_spec_without_options_retains_source_creation_budgets():
    spec=prepare_job({'site_polygon':site()})['job_spec'];spec.pop('options')
    result=prepare_job({'site_polygon':site(),'job_spec':spec})
    assert result['max_generations']==50 and result['population_size']==210
    assert 'options' not in result['job_spec']


def test_incomplete_custom_outputs_are_not_silently_discarded():
    with pytest.raises(JobSpecError) as error:
        prepare_job({'site_polygon':site(),'job_spec':{'outputs':[]}})
    assert error.value.code=='incomplete_specification'
