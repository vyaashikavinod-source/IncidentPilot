from incidentpilot.evaluation import toy_faults as faults


def test_model_receives_both_services_without_fault_label(monkeypatch):
    class FakeService:
        import threading
        lock=threading.Lock()
        logs=[{'event':'request_ok'}]
        config_limit=100
        delay=.002
        def metrics(self):return {'requests':5,'errors':0}
    calls=[]
    def decide(endpoint,model,messages,key):
        calls.append(messages.copy())
        return {'action':'diagnose','root_cause':'bad_config','affected_service':'gateway',
                'explanation':'Measured configuration requires review.','proposed_fix':'Review config.',
                'evidence_ids':['e3','e4']},{'prompt_tokens':1,'completion_tokens':1}
    monkeypatch.setattr(faults,'model_decision',decide)
    diagnosis,evidence,trace,usage=faults.investigate_v2({'gateway':FakeService(),'dependency':FakeService()},'http://localhost','test',None)
    assert len(evidence)==6
    assert {(r['service'],r['tool']) for r in evidence.values()}=={(s,t) for s in ['gateway','dependency'] for t in ['read_metrics','read_logs','read_config']}
    assert all(t['actor']=='coverage_policy' for t in trace[:6])
    assert 'expected_service' not in str(calls)
    assert len(usage)==1


def test_single_source_and_invented_counts_are_rejected(monkeypatch):
    class FakeService:
        import threading
        lock=threading.Lock()
        logs=[]
        config_limit=100
        delay=.002
        def metrics(self):return {'requests':5,'errors':0}
    decisions=iter([
        {'action':'diagnose','root_cause':'pool_exhaustion','affected_service':'gateway','explanation':'Pool pressure','proposed_fix':'Review.','evidence_ids':['e1']},
        {'action':'diagnose','root_cause':'pool_exhaustion','affected_service':'gateway','explanation':'50 requests are active.','proposed_fix':'Review.','evidence_ids':['e3','e4']},
        {'action':'diagnose','root_cause':'pool_exhaustion','affected_service':'gateway','explanation':'5 requests were observed.','proposed_fix':'Review.','evidence_ids':['e3','e4']}])
    monkeypatch.setattr(faults,'model_decision',lambda *_:(next(decisions),{}))
    diagnosis,_,trace,usage=faults.investigate_v2({'gateway':FakeService(),'dependency':FakeService()},'http://localhost','test',None)
    assert len(usage)==3
    assert sum('validation_error' in t for t in trace)==2


def test_completed_cases_are_durable_and_never_overwritten(tmp_path):
    import json
    import pytest
    target=tmp_path/'rules.json'
    report=faults.run(3,target)
    rows=[json.loads(line) for line in target.with_suffix('.jsonl').read_text().splitlines()]
    assert rows==report['runs']
    assert all(r['fault_verified'] and r['recovery_verified'] and not r['fix_executed'] for r in rows)
    with pytest.raises(ValueError,match='overwrite'):
        faults.run(3,target)
