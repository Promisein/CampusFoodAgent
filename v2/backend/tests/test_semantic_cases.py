import json
from pathlib import Path
import pytest

FIXTURE=Path(__file__).resolve().parents[1]/'data/fixtures/semantic_cases_v1.json'
CASES=json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_semantic_functional_cases(case):
    from app.evaluation.semantic_study import evaluate_case
    assert not evaluate_case(case)['errors']
