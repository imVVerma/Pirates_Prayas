"""M7.3 designer handoff gate: preserve working HTML/JS DOM contracts.

This checks the files a parallel design chat is permitted to edit, without
running a browser, downloading models, or altering the clinical backend.
"""
from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def inspect(name):
    source = (HERE / name).read_text(encoding='utf-8')
    parser = Tags()
    parser.feed(source)
    parser.close()
    return source, parser.tags


class FieldDesignerContract(unittest.TestCase):
    def test_worker_wizard_ids_and_steps(self):
        source, tags = inspect('field_intake.html')
        ids = {attrs['id']: (tag, attrs) for tag, attrs in tags if 'id' in attrs}
        required = {
            'progress', 'bar', 'back', 'next', 'feedback', 'preview',
            'age', 'area', 'duration', 'narrative', 'consent', 'synthetic',
            'reviewed', 'voiceConsent', 'speak', 'typeInstead', 'voiceStatus',
            'xrayReport', 'esrReport', 'doneMessage',
            'coughChoices', 'feverChoices', 'sweatsChoices', 'weightlossChoices',
        }
        required_steps = {
            'intro', 'age', 'sex', 'area', 'cough', 'duration', 'fever',
            'sweats', 'weightloss', 'narrative', 'tests', 'consent', 'review', 'done',
        }
        self.assertFalse(required - ids.keys(), f'missing worker controls: {required - ids.keys()}')
        for step in required_steps:
            tag, attrs = ids[f'step-{step}']
            self.assertEqual(tag, 'section', step)
            self.assertIn('step', attrs.get('class', '').split(), step)
        self.assertEqual(ids['age'][1].get('type'), 'number')
        self.assertEqual(ids['duration'][1].get('type'), 'number')
        self.assertEqual(ids['narrative'][0], 'textarea')
        for field in ('consent', 'synthetic', 'reviewed', 'voiceConsent'):
            self.assertEqual(ids[field][1].get('type'), 'checkbox', field)
        for field in ('xrayReport', 'esrReport', 'area'):
            self.assertEqual(ids[field][0], 'select', field)
        for field in ('xrayReport', 'esrReport'):
            options = [attrs['value'] for tag, attrs in tags if tag == 'option'
                       and 'value' in attrs and attrs['value'] in {'yes', 'no', 'unknown'}]
            for value in ('yes', 'no', 'unknown'):
                self.assertIn(value, options, f'{field}: missing {value} choice')
        radios = {(attrs.get('name'), attrs.get('value')) for tag, attrs in tags
                  if tag == 'input' and attrs.get('type') == 'radio'}
        self.assertIn(('language', 'en'), radios)
        self.assertIn(('language', 'hi'), radios)
        for choice in ('male', 'female', 'other', 'not_recorded'):
            self.assertIn(('sex', choice), radios)
        self.assertIn('/field_intake.js', source)
        self.assertIn('SYNTHETIC DEMO ONLY', source)
        self.assertIn('data-en=', source)
        self.assertIn('data-hi=', source)

    def test_saved_cases_contract(self):
        source, tags = inspect('field_cases.html')
        ids = {attrs['id'] for tag, attrs in tags if 'id' in attrs}
        for control in ('retry', 'refresh', 'cards', 'notice'):
            self.assertIn(control, ids)
        self.assertIn('/field_cases.js', source)
        self.assertIn('SYNTHETIC DEMO ONLY', source)

    def test_no_remote_runtime_dependencies_in_designer_files(self):
        for name in ('field_intake.html', 'field_cases.html'):
            with self.subTest(name=name):
                _, tags = inspect(name)
                for tag, attrs in tags:
                    if tag == 'script':
                        self.assertTrue(attrs.get('src', '').startswith('/'), attrs)
                    if tag == 'link' and attrs.get('rel') in ('stylesheet', 'preload'):
                        self.assertFalse(attrs.get('href', '').startswith(('http:', 'https:', '//')), attrs)


if __name__ == '__main__':
    unittest.main(verbosity=2)
