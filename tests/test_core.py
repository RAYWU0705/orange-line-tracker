import unittest
from datetime import timedelta
from core import *
from adapter import normalize
class CoreTests(unittest.TestCase):
 def setUp(self):
  self.s=dict(DEFAULTS);self.at=parse_time('2026-11-03T16:00:00+08:00')
 def row(self,car=401,time='2026-10-30T12:00:00+08:00',kind='service'):
  return {'car':car,'pair':pair(car),'time':time,'kind':kind,'run':'401','station':'景安','destination':'南勢角','note':'','source':''}
 def fleet(self,records,cov={},eng=[]):return summarize(records,cov,self.s,eng,self.at)[0]
 def test_pair(self):
  self.assertEqual(pair(402),401)
  with self.assertRaises(ValueError):pair(457)
 def test_midnight(self):self.assertEqual(opday('2026-11-03T01:30:00+08:00'),'2026-11-02')
 def test_cutoff(self):self.assertEqual(opday('2026-11-03T04:00:00+08:00'),'2026-11-03')
 def test_utc(self):self.assertEqual(opday('2026-11-02T17:30:00Z'),'2026-11-02')
 def test_branch(self):
  self.assertEqual(branch('401'),'迴龍／南勢角');self.assertEqual(branch('430'),'蘆洲／南勢角');self.assertEqual(branch('421'),'未判定')
 def test_unknown(self):
  f=self.fleet([]);self.assertEqual(f['status'],'尚無紀錄');self.assertIsNone(f['days']);self.assertEqual(f['maintenance'],[])
 def test_pair_preserves_observed(self):
  f=self.fleet([self.row(402)]);self.assertEqual(f['cars'],[401,402]);self.assertEqual(f['last']['car'],402)
 def test_no_coverage(self):self.assertEqual(self.fleet([self.row()])['maintenance'],[])
 def test_overlap(self):
  f=self.fleet([self.row(time='2026-10-31T12:00:00+08:00')],{'2026-11-01':1,'2026-11-02':1});self.assertEqual(f['maintenance'],['三級檢修','四級檢修'])
 def test_partial_coverage(self):self.assertEqual(self.fleet([self.row()],{'2026-11-01':1,'2026-11-02':1})['maintenance'],[])
 def test_long_gap(self):self.assertFalse(self.fleet([self.row(time='2026-09-01T12:00:00+08:00')],{(self.at-timedelta(days=i)).date().isoformat():1 for i in range(1,31)})['gap_complete'])
 def test_offpeak(self):self.assertEqual(self.fleet([self.row(time='2026-11-02T12:00:00+08:00')])['maintenance'],[])
 def test_nonservice(self):
  self.assertIsNone(self.fleet([self.row(kind='test')])['last']);self.assertFalse(self.fleet([self.row(kind='depot')])['today'])
 def test_live(self):
  self.assertTrue(self.fleet([self.row(time='2026-11-03T15:55:00+08:00')])['live']);self.assertFalse(self.fleet([self.row(time='2026-11-03T15:00:00+08:00')])['live'])
 def test_today(self):self.assertTrue(self.fleet([self.row(time='2026-11-03T07:00:00+08:00')])['today'])
 def test_recovery(self):
  f=self.fleet([self.row()],eng=[{'pair':401,'start':'2026-10-01T12:00:00+08:00','state':'施工中'}]);self.assertTrue(f['engineering']['recovered']);self.assertEqual(f['engineering']['state'],'施工中')
 def test_probability_missing(self):self.assertIsNone(self.fleet([self.row()])['prediction']['probability'])
 def test_probability(self):
  cov={(self.at-timedelta(days=i)).date().isoformat():1 for i in range(1,15)};f=self.fleet([self.row()],cov);self.assertEqual(f['prediction']['n'],14);self.assertEqual(f['prediction']['k'],1);self.assertEqual(f['prediction']['probability'],12)
 def test_today_not_sample(self):self.assertEqual(self.fleet([self.row()],{'2026-11-03':1})['prediction']['n'],0)
 def test_maintenance_edges(self):
  self.assertEqual(maintenance(8),[]);self.assertEqual(maintenance(14),['五級檢修／大修']);self.assertEqual(maintenance(1),[])
 def test_adapter(self):
  c={'items_path':'data','fields':{'car':'Consist','time':'Time','run':'TrainNumber'},'car_map':{'A':402},'time_format':'%Y%m%d%H%M%S'};d=normalize({'data':[{'Consist':'A','Time':'20261103120000','TrainNumber':'430'}]},c)['observations'][0];self.assertEqual(d['car'],402);self.assertEqual(d['run'],'430')
 def test_no_guess(self):
  with self.assertRaises(ValueError):normalize([{'TrainNumber':401}],{'fields':{'run':'TrainNumber'}})
