import json

from incidentpilot.evaluation.toy_faults import FAULTS, run


def test_real_faults_and_recovery_are_recorded_without_model_claims(tmp_path):
    report = run(3, tmp_path / 'runs.json')
    assert report['agent_type'] == 'deterministic_rules_baseline'
    assert report['faults_verified'] == report['recoveries_verified'] == 3
    assert {r['fault'] for r in report['runs']} == set(FAULTS)
    assert report['input_tokens'] == report['output_tokens'] == 0
    for record in report['runs']:
        assert record['fix_executed'] is False
        assert record['healthy_control_metrics']['errors'] == 0
        assert record['time_to_diagnosis_seconds'] > 0
        assert all(code >= 500 for code in record['http_statuses'])
        assert 'fault' not in json.dumps(record['evidence'])
