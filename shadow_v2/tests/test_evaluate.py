import unittest
from datetime import date,timedelta
from shadow_v2.evaluate import evaluate


def event(item, label, sequence, day='2026-09-30'):
    return {'item_id': item, 'label': label, 'server_sequence': sequence,
            'event_id': str(sequence), 'edition_date': day, 'provenance': 'explicit_feedback'}


class EvaluationTest(unittest.TestCase):
    def test_unknown_is_not_negative_and_no_claimed_precision(self):
        result = evaluate({'ranked_item_ids': ['a','b','c'], 'feedback_events': [event('a','used',1)]})
        top = result['top_5']
        self.assertEqual(top['unknown'], 2)
        self.assertIsNone(top['used_precision'])
        self.assertEqual(top['used_precision_bounds'], [1/3,1])
        self.assertIsNone(result['on_time'])
        self.assertFalse(result['formal_review']['eligible'])

    def test_all_labeled_precision_and_confirmed_match_ranks(self):
        result=evaluate({'ranked_item_ids':['b','a'], 'feedback_events':[event('a','used',1),event('b','not_relevant',2)],
                         'reviewed_v1_matches':[{'confirmed':True,'v1_item_id':'a','v2_item_id':'a'}]})
        self.assertEqual(result['top_5']['used_precision'],.5)
        self.assertEqual(result['used_v1_story_ranks'][0]['v2_rank'],2)

    def test_clear_and_historical_overlap_do_not_become_used(self):
        result=evaluate({'ranked_item_ids':['a','b'], 'feedback_events':[
            event('a','used',1),event('a','cleared',2),dict(event('b','used',3),provenance='historical_overlap')]})
        self.assertEqual(result['top_5']['unknown'],2)
        self.assertEqual(result['formal_review']['labeled_trading_editions'],0)

    def test_both_eligibility_requirements_and_no_auto_promotion(self):
        days=[date(2026,9,1)+timedelta(days=i) for i in range(28)]
        days=[day.isoformat() for day in days if day.weekday()<5]
        events=[event(str(i),'used',i,days[i%20]) for i in range(100)]
        result=evaluate({'ranked_item_ids':[], 'feedback_events':events})
        self.assertTrue(result['formal_review']['eligible'])
        self.assertFalse(result['promotion_authorized'])
        events[-1]['event_id']=events[0]['event_id']
        self.assertFalse(evaluate({'feedback_events':events})['formal_review']['eligible'])

    def test_runtime_requires_aware_chronological_observation(self):
        result=evaluate({'started_at':'2026-10-01T06:35:00+08:00','finished_at':'2026-10-01T06:39:30+08:00'})
        self.assertEqual(result['generation_seconds'],270)
        self.assertIsNone(result['copied_without_edit']['rate_among_reviewed'])
        with self.assertRaises(ValueError):evaluate({'started_at':'2026-10-01T06:35:00','finished_at':'2026-10-01T06:39:30'})


if __name__=='__main__':unittest.main()
