"""Replay scripted semantic contracts, never a model comprehension benchmark."""
import argparse
import json
from pathlib import Path
import tempfile

from app import artifact_io
from app.agent.semantic import interpret
from app.agent.state import initial_state

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_CASES=ROOT/'data/fixtures/semantic_cases_v1.json'


def evaluate_case(case):
    state=initial_state({'latitude':0,'longitude':0})
    result=interpret({'action':'search','index':None,'changes':case['changes'],
                      'issues':case.get('issues',[]),'resolved':[]},state,case['message'])
    errors=[]
    if bool(result['issues'])!=case['expect_issue']:errors.append('issue')
    for expected,key in [('expect_topics','topics'),('expect_include','include'),('expect_exclude','exclude'),
                         ('expect_price','max_price_level'),('expect_radius','radius_km')]:
        if expected in case and result['slots'][key]!=case[expected]:errors.append(key)
    return {'case':case['id'],'slots':result['slots'],'issues':result['issues'],'errors':errors}


def run_study(cases_path,output_dir):
    cases_path,output_dir=Path(cases_path).resolve(),Path(output_dir).resolve()
    if output_dir==cases_path.parent or output_dir in cases_path.parents or cases_path.parent in output_dir.parents:
        raise ValueError('Output overlaps fixtures')
    if output_dir.exists():
        previous=artifact_io.verify_artifacts(output_dir,'experiment_manifest.json')
        if previous['experiment_id']!='semantic_v2_scripted':raise ValueError('Unrelated output directory')
    fixture=json.loads(cases_path.read_text(encoding='utf-8'))
    results=[evaluate_case(case) for case in fixture['cases']]
    report={'experiment_id':'semantic_v2_scripted','cases':len(results),
            'passed':sum(not r['errors'] for r in results),'provider_calls':0,'scope':fixture['scope'],
            'claims':'schema/slot/issue contracts with scripted model outputs; not measured open-ended language accuracy'}
    output_dir.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.semantic-',dir=output_dir.parent) as temporary:
        stage=Path(temporary)
        for name,value in [('metrics.json',report),('case_results.json',results)]:
            (stage/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        manifest={'experiment_id':'semantic_v2_scripted','cases_sha256':artifact_io.file_sha256(cases_path),
                  'code_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):artifact_io.file_sha256(p) for p in sorted((ROOT/'app').rglob('*.py'))}}
        artifact_io.publish_directory(stage,output_dir,manifest,'experiment_manifest.json')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=DEFAULT_CASES)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'data/derived/semantic_v2_acceptance')
    args=parser.parse_args(argv)
    report=run_study(args.cases,args.output_dir)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['passed']==report['cases'] else 1


if __name__=='__main__':raise SystemExit(main())
