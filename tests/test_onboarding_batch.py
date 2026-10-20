"""Atomic batches reduce committed public mutations while preserving every guard."""
import json
import pytest
from course_tutor.api import LumenCore
from course_tutor.errors import ValidationError, IdempotencyConflictError


def setup(tmp_path, name):
    core=LumenCore(tmp_path/name)
    core.create_course('SYNTHETIC',course_id='s',request_id='course')
    file=tmp_path/(name+'.txt');file.write_text('SYNTHETIC exercise prompts and context.')
    sid=core.ingest_source('s',file,catalog_questions=False,request_id='source')['data']['source_version_id']
    items=[{'operation':'catalog_candidate','source_version_id':sid,
            'question':{'question_key':str(n),'question_text':f'Compute synthetic value {n}.',
                        'source_spans':[{'section_index':0}]},'metadata':{'points':n,'question_type':'open'}} for n in range(1,5)]
    return core,items


def receipts(core):
    return core.con.execute('SELECT count(*) FROM operation_receipts').fetchone()[0]


def test_batch_vs_old_mutation_counts(tmp_path):
    old,items=setup(tmp_path,'old')
    new,batch=setup(tmp_path,'new')
    try:
        for n,item in enumerate(items):
            old.catalog_exam_questions('s',item['source_version_id'],[item['question']],request_id=f'catalog{n}')
            q=next(q for q in old.list_questions('s')['questions'] if q['question_key']==str(n+1))
            old.annotate_question('s',q['id'],q['revision'],item['metadata'],request_id=f'meta{n}')
        r=new.batch_questions('s',batch,request_id='batch')
        assert (receipts(old),receipts(new))==(10,3)
        assert len(new.list_questions('s')['questions'])==4
        replay=new.batch_questions('s',batch,request_id='batch')
        assert replay['data']==r['data'] and replay['idempotent_replay']
        with pytest.raises(IdempotencyConflictError):
            new.batch_questions('s',batch[:-1],request_id='batch')
        print('Mutation receipts including identical course+source setup: old=10, batch=3; candidate/metadata phase old=8, batch=1.')
    finally:
        old.close();new.close()


def test_all_invalid_items_reported_and_whole_batch_rolls_back(tmp_path):
    c,items=setup(tmp_path,'atomic')
    try:
        items[1]['metadata']={'points':-1}
        items[3]['source_version_id']='not-in-this-course'
        before=receipts(c)
        with pytest.raises(ValidationError) as error:
            c.batch_questions('s',items,request_id='bad')
        assert [e['index'] for e in error.value.details['rejected_items']]==[1,3]
        assert not c.list_questions('s')['questions'] and receipts(c)==before
        # No failed receipt survives; corrected payload can reuse the same ID.
        items[1]['metadata']={'points':2};items[3]['source_version_id']=items[0]['source_version_id']
        c.batch_questions('s',items,request_id='bad')
    finally:
        c.close()


def test_retry_context_noop_revision_and_renewed_acceptance(tmp_path):
    c,items=setup(tmp_path,'guards')
    try:
        c.batch_questions('s',items[:1],request_id='catalog')
        q=c.list_questions('s')['questions'][0];vid=q['exercise_version_id']
        c.review_question_occurrence('s',q['id'],q['revision'],'accepted','Checked stem')
        changed=c.update_exercise_version(vid,question_text='Compute synthetic value 1.',context_blocks=['Shared setup'],expected_revision=1)
        assert changed['changed'] and changed['current_revision']==2
        same=c.update_exercise_version(vid,question_text=changed['question_text'],context_blocks=['Shared setup','Shared setup'],expected_revision=2)
        assert not same['changed'] and same['current_revision']==2
        assert same['question_text'].count('Shared setup')==1
        with pytest.raises(ValidationError,match='renewed review_question_occurrence'):
            c.validate_exercise_version(vid,expected_revision=2,checks={'checked':True})
        q=c.list_questions('s')['questions'][0]
        c.review_question_occurrence('s',q['id'],q['revision'],'accepted','Renewed comparison with shared setup')
        c.validate_exercise_version(vid,expected_revision=same['current_revision'],checks={'checked':True},reference_solution='SYNTHETIC checked answer',rubric={'max_points':1})
    finally:
        c.close()


def test_metadata_batch_retains_stale_revision_and_course_guards(tmp_path):
    c,items=setup(tmp_path,'metadata')
    try:
        c.batch_questions('s',items[:2],request_id='seed')
        questions=c.list_questions('s')['questions']
        a,b=questions
        payload=[{'operation':'annotate','occurrence_id':a['id'],'expected_revision':a['revision'],'metadata':{'points':9}},
                 {'operation':'annotate','occurrence_id':b['id'],'expected_revision':b['revision']+1,'metadata':{'points':9}}]
        with pytest.raises(ValidationError) as error:
            c.batch_questions('s',payload,request_id='stale')
        assert error.value.details['rejected_items'][0]['index']==1
        assert c.list_questions('s')['questions']==questions
        c.create_course('OTHER SYNTHETIC',course_id='other')
        with pytest.raises(ValidationError):
            c.batch_questions('other',payload,request_id='cross')
    finally:
        c.close()
