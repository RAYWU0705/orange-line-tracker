import unittest
from metro_web import parse_page
class WebTests(unittest.TestCase):
 def html(self,stamp='2026/11/3 下午 05:36:16',rows=''):
  return '<span id="lblData">更新日期時間：'+stamp+'</span>'+rows
 def train(self,cars='450/449',dest='O-蘆洲站',show=True):
  return f'<div class="train__item {"show" if show else ""}" data-cartweight="O-up-{cars}"><div><img alt="{dest}" src="destination.svg"></div></div>'
 def test_real_attributes(self):
  d=parse_page(self.html(rows=self.train()));self.assertEqual(d['observations'][0]['car'],450);self.assertEqual(d['observations'][0]['destination'],'蘆洲');self.assertEqual(d['updated'],'2026-11-03T17:36:16+08:00')
 def test_midnight(self):self.assertIn('T00:36:16',parse_page(self.html('2026/11/3 上午 12:36:16',self.train()))['updated'])
 def test_duplicate(self):self.assertEqual(len(parse_page(self.html(rows=self.train()+self.train('449/450')))['observations']),1)
 def test_outside(self):
  d=parse_page(self.html(rows=self.train('457/458')+self.train('305/306')));self.assertEqual(d['observations'],[]);self.assertEqual(len(d['outside']),2)
 def test_hidden(self):
  d=parse_page(self.html(rows=self.train()+self.train('401/402',show=False)));self.assertEqual(len(d['observations']),1)
 def test_blank(self):
  with self.assertRaises(ValueError):parse_page(self.html())
 def test_missing_time(self):
  with self.assertRaises(ValueError):parse_page(self.html('時間不明',self.train()))
