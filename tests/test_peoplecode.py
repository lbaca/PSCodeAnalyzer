"""PeopleCode analysis tests."""

import os.path
import pscodeanalyzer.engine as psca


_TESTS_DIR = os.path.dirname(__file__)
_SETTINGS_FILE = os.path.join(_TESTS_DIR, psca.default_config_file_name)


def test_app_class_1():
    source_file = (os.path.join(_TESTS_DIR, 'HRMH_SETUP.HRMHServices.ppl'), 58)
    file_reports = psca.analyze([source_file], _SETTINGS_FILE,
                                profile='test_01')
    reports = file_reports[0].reports
    found_errors = set(r.line for r in reports)
    expected_errors = {
        755,
        980,
        1230,
        1232,
        1275,
        1281,
        1392,
        1410,
        1416,
        1443,
        1449,
        1572,
        2004,
        2372,
        3459,
        3602,
        3635,
        3758,
        3819,
        4289,
        4304,
        4321,
        4400,
        4408,
        4432,
        4434,
    }
    undetected_errors = expected_errors - found_errors
    assert len(undetected_errors) == 0, \
        f'Undetected errors on line(s) {undetected_errors}'
    unexpected_errors = found_errors - expected_errors
    assert len(unexpected_errors) == 0, \
        f'Unexpected errors on line(s) {unexpected_errors}'


def test_program_1():
    source_file = (
        os.path.join(_TESTS_DIR, 'PTPG_WORKREC.FUNCLIB.FieldFormula.ppl'),
        None,
        [(850, 853)]
    )
    file_reports = psca.analyze([source_file], _SETTINGS_FILE,
                                profile='test_02')
    reports = file_reports[0].reports
    # The elements of the found_errors and expected_errors sets are
    # tuples with three elements: (<rule code>, <line>, <column>)
    found_errors = set((r.rule_code, r.line, r.column) for r in reports)
    expected_errors = {
        (2, 852, 13),
        (3, 850, 16),
        (3, 850, 37),
        (3, 850, 78),
        (3, 850, 95),
        (3, 852, 225),
        (3, 852, 246),
        (3, 852, 288),
        (3, 852, 309),
        (3, 852, 351),
        (3, 852, 372),
        (3, 852, 414),
        (3, 852, 435),
        (3, 852, 477),
        (3, 852, 498),
        (3, 853, 21),
        (3, 853, 42),
    }
    undetected_errors = expected_errors - found_errors
    assert len(undetected_errors) == 0, \
        f'Undetected errors: {undetected_errors}'
    unexpected_errors = found_errors - expected_errors
    assert len(unexpected_errors) == 0, \
        f'Unexpected errors: {unexpected_errors}'
