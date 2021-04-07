"""Static code analyzer engine with configurable plug-in rules."""

import argparse
import glob
import importlib
import json
import logging
import mmap
import os.path
import platform
import re
import sys
from abc import ABC, abstractmethod
from collections import namedtuple
from collections.abc import Iterable
from enum import Enum


# GLOBAL VARIABLES
_verbose = False
_logger = logging.getLogger('engine')
_config_evaluators = None
default_config_file_name = 'settings.json'


# MODEL
Interval = namedtuple('Interval', ['start', 'end'])


class ReportType(Enum):
    """Enumeration of report types."""

    ERROR = 'E'
    WARNING = 'W'
    INFO = 'N'


class FileReports:
    """Pointer to a file path and its analysis reports."""

    def __init__(self, file_path, source_type=None, reports=[]):
        """Create a FileReports object."""
        self.file_path = file_path
        self.source_type = source_type
        self.reports = reports

    def __str__(self):
        """Return a string representation of the object."""
        out = self.basename
        if self.source_type is not None:
            out += f' ({str(self.source_type)})'
        if self.reports:
            out += f': {self.cumulative_status.name}'
            for r in self.reports:
                out += f'\n - {str(r)}'
        else:
            out += ': no reports'
        return out

    @property
    def basename(self):
        """Return the file name from the path."""
        return os.path.basename(self.file_path)

    @property
    def cumulative_status(self):
        """Return the cumulative status of the reports."""
        status = ReportType.INFO
        for r in self.reports:
            if r.is_error:
                status = ReportType.ERROR
                break
            elif r.is_warning:
                status = ReportType.WARNING
        return status

    @property
    def is_error(self):
        """Return whether any reports are in error status."""
        return (self.cumulative_status == ReportType.ERROR)


class Report:
    """A report about a rule with regard to a source file.

    - rule_code is the code of the rule which produced the report (can
      be None for special cases, such as parsers that wish to report
      parsing errors).
    - message is the one-line text to summarize the report.
    - report_type must be one of the ReportType enumeration values.
    - line and column indicate where in the source file the code of
      interest can be found.
    - text is the code of interest, which could span multiple lines.
    - detail is a more descriptive message regarding the report.
    """

    def __init__(self, rule_code, message, report_type=ReportType.ERROR,
                 line=None, column=None, text=None, detail=None):
        """Create a report."""
        self.rule_code = rule_code
        self.message = message
        self.type = report_type
        self.line = line
        self.column = column
        self.text = text
        self.detail = detail

    def __str__(self):
        """Return a string representation of the report.

        Typically used for summaries.
        """
        if self.rule_code is None:
            out = f'[{self.type.name}]'
        elif type(self.rule_code) is int:
            out = f'[{self.type.value}{self.rule_code:04d}]'
        else:
            out = f'[{self.type.name}:{self.rule_code}]'

        if self.is_error:
            out += ' Error'
        elif self.is_warning:
            out += ' Warning'
        elif self.is_info:
            out += ' Information'

        if self.line is None:
            if self.column is not None:
                out += f' at position {self.column}'
        else:
            out += f' on line {self.line}'
            if self.column is not None:
                out += f', column {self.column}'

        if self.message:
            out += f': {self.message}'

        return out

    @property
    def is_error(self):
        """Return True if the report is an error."""
        return (self.type == ReportType.ERROR)

    @property
    def is_warning(self):
        """Return True if the report is a warning."""
        return (self.type == ReportType.WARNING)

    @property
    def is_info(self):
        """Return True if the report is informational."""
        return (self.type == ReportType.INFO)


class Evaluator(ABC):
    """Abstract base class for all evaluators (rules and proxies).

    The following configuration options apply:
    - "class": the name of the class to instantiate (should be "Rule",
      "RegexRule", "Proxy", or a fully-qualified subclass of any of
      these)
    - "description": used as the description for the evaluator instance
      (optional)
    """

    def __init__(self, config):
        """Construct an evaluator with the given configuration."""
        self.config = config
        self.description = config.get('description')
        self.intervals = []
        _logger.debug(f'Instantiated {self.__class__.__name__}')

    @abstractmethod
    def reset(self):
        """Reset the evaluator for a new evaluation.

        To be implemented by subclasses, usually when proxied. Should
        not be called from the constructor because subclasses may wish
        to reset members that are not yet defined.
        """
        pass

    def add_interval_str(self, interval):
        """Add an interval for evaluator applicability from a string.

        The interval value can be one of the following:

        - m-n: results in an interval between m and n
        - m- : results in an interval between m and the end of the input
        - m  : results in an interval only for m (same as m-m)
        """
        if interval:
            from_location = None
            to_location = None
            try:
                if '-' in interval:
                    parts = interval.split('-', maxsplit=1)
                    if 1 <= len(parts) <= 2:
                        if len(parts[0] > 0):
                            from_location = int(parts[0])
                            if len(parts) == 2:
                                if len(parts[1] > 0):
                                    to_location = int(parts[1])
                else:
                    from_location = int(interval)
                if from_location:
                    self.add_interval(from_location, to_location)
                else:
                    _logger.warning(f'Invalid interval: "{interval}"')
            except ValueError:
                _logger.warning(f'Invalid interval: "{interval}"')

    def add_interval(self, from_location, to_location):
        """Add an interval for evaluator applicability.

        The interval would typically refer to line numbers, but
        subclasses can override as required.

        If to_location is None, the interval is until the end of the
        input. Overlaps are not resolved in any way.
        """
        if (from_location
                and (to_location is None
                     or from_location <= to_location)):
            self.intervals.append(Interval(from_location, to_location))
        else:
            _logger.warning('Invalid interval')

    def is_position_in_intervals(self, position_start, position_end=None):
        """Determine if the given position is within targeted intervals.

        Returns True if position is included within any of the
        configured intervals, or if no intervals have been configured.
        """
        if self.intervals:
            end = position_start if position_end is None else position_end
            for interval in self.intervals:
                compare_end = end if interval.end is None else interval.end
                if position_start <= compare_end and end >= interval.start:
                    return True
            else:
                return False
        else:
            return True

    @abstractmethod
    def evaluate(self):
        """Evaluate the evaluator, itself a Rule or a Proxy.

        Subclasses are free to define additional arguments for this
        method (e.g., Rules may want to interact with individual files,
        while Proxies may want to interact with pre-attached files).

        Returns a list of Report objects.
        """
        pass

    @property
    @abstractmethod
    def is_proxy(self):
        """Return True if the evaluator is a proxy."""
        pass

    @property
    @abstractmethod
    def rule_count(self):
        """Return the number of rules included in this evaluator."""
        pass


class Rule(Evaluator):
    """Abstract base class for code analyzer rules.

    The following configuration options apply:
    - "code": an integer between 1 and 9999 that uniquely identifies the
      rule
    - "description": additionally used as the default message for
      reports (optional, defaults to None)
    - "default_report_type": one of "ERROR" (default), "WARNING" or
      "INFO" (optional)
    - "include_source_types": a list of integers that identify the
      source types that this rule applies to; if empty (default), all
      source types apply (optional)
    - "exclude_source_types": a list of integers that identify the
      source types that this rule does not apply to; if a source type is
      an explicit member of both lists, it is excluded (optional)
    """

    def __init__(self, config):
        """Construct a rule with the given configuration."""
        super(Rule, self).__init__(config)
        self.code = int(config['code'])
        if self.code <= 0:
            raise ValueError('code must be a positive integer')
        default_report_type = config.get('default_report_type', 'ERROR')
        if hasattr(ReportType, default_report_type):
            self.default_report_type = getattr(ReportType, default_report_type)
        else:
            raise ValueError('invalid default_report_type: '
                             f'"{default_report_type}"')
        self.default_message = self.description
        self.include_source_types = config.get('include_source_types', [])
        self.exclude_source_types = config.get('exclude_source_types', [])

    def reset(self):
        """Reset the rule for a new evaluation."""
        super(Rule, self).reset()
        self.intervals = []

    def applies_to_source_type(self, source_type):
        """Return True if this Rule applies to the provided source type."""
        applies = True
        if source_type is not None:
            if self.include_source_types:
                applies = (source_type in self.include_source_types)
            applies = (applies
                       and (source_type not in self.exclude_source_types))
        return applies

    def evaluate(self, source):
        """Evaluate the rule against the referenced source.

        source can be a path to a file or an open file-like object.
        Subclasses are free to treat source differently (e.g., a string
        with the code to analyze, a parse tree, etc.).

        Returns a list of Report objects.
        """
        _logger.debug(f'Evaluating {self.__class__.__name__}')
        if source is None:
            raise ValueError(f'"{source}" cannot be None')
        if type(source) is str:
            if os.path.isfile(source):
                with open(source) as source_file:
                    reports = self.evaluate_file(source_file)
            else:
                raise ValueError(f'"{source}" not found or not a file')
        else:
            reports = self.evaluate_file(source)
        return reports

    def evaluate_file(self, source_file):
        """Evaluate the rule against the provided file-like object.

        The file must already be open.

        Returns a list of Report objects.
        """
        # Abstract class, do nothing; not identified as @abstractmethod
        # because subclasses are not required to implement this method
        # (e.g., when called through a Proxy)
        return []

    @property
    def is_proxy(self):
        """Return True if the evaluator is a proxy."""
        return False

    @property
    def rule_count(self):
        """Return the number of rules included in this evaluator."""
        return 1


class RegexRule(Rule):
    """Base class for code analyzer rules based on regular expressions.

    The following configuration options apply:
    - "pattern": a string with the pattern to search for
    - "invert": a boolean indicating if the match should be inverted; if
      false (default), matches of the pattern are reported; if true, a
      single report is raised if the pattern is not matched (optional)
    """

    def __init__(self, config):
        """Construct a rule with the given configuration."""
        super(RegexRule, self).__init__(config)
        if config is None:
            raise ValueError('no configuration provided')
        pattern = config.get('pattern')
        if pattern:
            if type(pattern) is str:
                self.regex = re.compile(pattern.encode())
            elif type(pattern) is bytes:
                self.regex = re.compile(pattern)
            else:
                raise ValueError('unexpected type for pattern: '
                                 f'{type(pattern)}')
        else:
            raise ValueError('empty pattern is not allowed')
        self.invert = config.get('invert', False)
        default_msg = f'Pattern {"not " if self.invert else ""}matched'
        self.default_message = config.get('description', default_msg)

    def __str__(self):
        """Return a string representation of the rule."""
        return (f'{self.__class__.__name__} = {"{"}pattern: '
                f'"{self.regex.pattern.decode()}", invert: {self.invert}, '
                f'default_message: "{self.default_message}"{"}"}')

    def evaluate(self, source):
        """Evaluate the rule against the referenced source.

        source can be a path to a file or an open file-like object.
        Subclasses are free to treat source differently (e.g., a string
        with the code to analyze, a parse tree, etc.). Unlike its
        superclass, RegexRule treats files in binary mode.

        Returns a list of Report objects.
        """
        _logger.debug(f'Evaluating {self.__class__.__name__}')
        if source is None:
            raise ValueError(f'"{source}" cannot be None')
        if type(source) is str:
            if os.path.isfile(source):
                with open(source, 'rb') as source_file:
                    reports = self.evaluate_file(source_file)
            else:
                raise ValueError(f'"{source}" not found or not a file')
        else:
            reports = self.evaluate_file(source)
        return reports

    def evaluate_file(self, source_file):
        """Evaluate the rule against the provided file-like object.

        The file must already be open.

        Returns a list of Report objects.
        """
        reports = []
        try:
            contents = mmap.mmap(source_file.fileno(), 0,
                                 access=mmap.ACCESS_READ)
            empty = False
        except ValueError:
            empty = True
        if not empty:
            if self.invert and not self.intervals:
                match = self.regex.search(contents)
                # Not matching is an error
                if not match:
                    pattern_str = self.regex.pattern.decode()
                    report = Report(
                        self.code, self.default_message,
                        report_type=self.default_report_type,
                        detail=f'The pattern "{pattern_str}" was not found.')
                    reports.append(report)
            else:
                matches = self.regex.finditer(contents)
                for match in matches:
                    start = match.start()
                    end = match.end()
                    contents.seek(0)
                    before = contents.read(start).decode()
                    text = contents.read(end - start).decode()
                    line_start = before.count('\r') + 1
                    if line_start == 1:
                        # Match starts on line 1
                        column = start + 1
                    else:
                        # Match starts on another line
                        last_newline = before.rfind('\n')
                        if last_newline == -1:
                            last_newline = before.rfind('\r')
                        column = start - last_newline
                    if self.intervals:
                        # Calculate end line of match
                        line_end = line_start + text.rstrip('\r\n').count('\r')
                    else:
                        # End line is unimportant
                        line_end = line_start
                    if self.is_position_in_intervals(line_start,
                                                     position_end=line_end):
                        if self.invert:
                            break
                        else:
                            report = Report(
                                self.code, self.default_message,
                                report_type=self.default_report_type,
                                line=line_start, column=column,
                                text=text)
                            reports.append(report)
                else:
                    if self.invert:
                        pattern_str = self.regex.pattern.decode()
                        report = Report(
                            self.code, self.default_message,
                            report_type=self.default_report_type,
                            detail=(f'The pattern "{pattern_str}" was not '
                                    'found.'))
                        reports.append(report)
        return reports


class Proxy(Evaluator):
    """Proxy class for grouping evaluators.

    Proxies will typically be used to avoid processing the same file
    multiple times during load.

    The following configuration options apply:
    - "evaluators": a list of configurations for evaluators that will be
      executed in the stated order
    """

    def __init__(self, config):
        """Construct a PeopleCode parser proxy for the given file.

        Initialization will be lazy.
        """
        super(Proxy, self).__init__(config)
        self.file_path = None
        self.source_type = None
        self.evaluators = [_create_evaluator(ev) for ev in
                           config['evaluators']]

    def __str__(self):
        """Return a string representation of the proxy."""
        out = self.__class__.__name__ + ' = {evaluators: ['
        for i, ev in enumerate(self.evaluators):
            if i > 0:
                out += ', '
            out += ev.__class__.__name__
        out += ']}'
        return out

    def reset(self):
        """Reset the proxy for a new source."""
        for ev in self.evaluators:
            ev.reset()
            ev.intervals = self.intervals.copy()

    def attach(self, file_path, source_type=None):
        """Attach the Proxy to a specific file and reset it.

        Does nothing if already attached to that file.
        """
        self.source_type = source_type
        if (self.file_path is None
                or not os.path.samefile(self.file_path, file_path)):
            self.file_path = file_path
            for ev in self.evaluators:
                if ev.is_proxy:
                    ev.attach(file_path, source_type=source_type)
            self.reset()

    def _evaluate_evaluator(self, evaluator, exhaustive):
        """Evaluate an evaluator, returning its reports."""
        if evaluator.is_proxy:
            return self._evaluate_proxy(evaluator, exhaustive)
        else:
            return self._evaluate_rule(evaluator)

    def _evaluate_rule(self, rule):
        """Evaluate a rule, returning its reports."""
        return rule.evaluate(self.file_path)

    def _evaluate_proxy(self, proxy, exhaustive):
        """Evaluate a proxy, returning its reports."""
        return proxy.evaluate(exhaustive=exhaustive)

    def _propagate_state(self, previous_ev, current_ev):
        """Propagate state to another evaluator.

        Abstract method allowing subclasses to copy state from one
        evaluator to the next if necessary. Not declared as an
        @abstractmethod because subclasses may wish to never propagate.
        """
        pass

    def evaluate(self, exhaustive=False):
        """Evaluate the proxied evaluators against the attached file path.

        Returns a list of Report objects.
        """
        _logger.debug(f'Evaluating {self.__class__.__name__}')
        all_reports = []
        if self.file_path:
            for i, ev in enumerate(self.evaluators):
                if i > 0:
                    self._propagate_state(self.evaluators[i - 1], ev)
                if ev.is_proxy or ev.applies_to_source_type(self.source_type):
                    reports = self._evaluate_evaluator(ev, exhaustive)
                    if reports:
                        all_reports.extend(reports)
                        if not exhaustive:
                            for r in reports:
                                if r.is_error:
                                    break
                            else:
                                # Inner loop did not break
                                continue
                            # Inner loop ended in break
                            break
        return all_reports

    @property
    def is_proxy(self):
        """Return True if the evaluator is a proxy."""
        return True

    @property
    def rule_count(self):
        """Return the number of rules included in this evaluator."""
        count = 0
        for ev in self.evaluators:
            count += ev.rule_count
        return count


# PRIVATE FUNCTIONS
def _print_verbose(text, end='\n', flush=True):
    """Print to stdout if verbose output is enabled."""
    if _verbose:
        print(text, end=end, flush=flush)


def _load_config(path, profile, substitutions):
    """Load the configuration from a JSON file."""
    _logger.info(f'Loading profile "{profile}" from file "{path}"')
    if os.path.isfile(path):
        with open(path) as config_file:
            config = json.load(config_file)
            if config:
                config_profile = config['profiles'][profile]
                config_subs = config_profile.get('substitutions')
                global _config_evaluators
                _config_evaluators = config_profile['evaluators']
                if config_subs or substitutions:
                    subs = dict(config_subs)
                    if substitutions:
                        subs.update(substitutions)
                    for ev in _config_evaluators:
                        _do_config_substitutions(ev, subs)
    else:
        raise ValueError(f'File "{path}" not found')


def _do_config_substitutions(config, substitutions):
    """Perform configuration value substitutions from a dictionary.

    This function will be called recursively, where config will be
    either a dictionary loaded from JSON or a list of such dictionaries.
    """
    if substitutions:
        if isinstance(config, dict):
            # Loop over dictionary elements
            for key in iter(config):
                val = config[key]
                if isinstance(val, (dict, list)):
                    _do_config_substitutions(val, substitutions)
                elif isinstance(val, str):
                    for old in iter(substitutions):
                        val = val.replace(f'#{old}#', substitutions[old])
                    config[key] = val
        elif isinstance(config, list):
            # Loop over list items recursively
            for item in config:
                _do_config_substitutions(item, substitutions)


def _create_evaluator(config):
    """Create an evaluator based on the given configuration."""
    class_name = config['class']
    parts = class_name.rsplit(sep='.', maxsplit=1)
    if len(parts) == 1:
        _logger.debug(f'Creating evaluator {parts[-1]}')
        ev = globals()[parts[-1]](config)
    else:
        module = sys.modules.get(parts[0])
        if not module:
            _logger.debug(f'Importing module {parts[0]}')
            module = importlib.import_module(parts[0])
        _logger.debug(f'Creating evaluator {parts[-1]}')
        ev = getattr(module, parts[-1])(config)
    return ev


def _flatten(lst):
    """Generate individual items from a multiple-level list."""
    for elem in lst:
        if isinstance(elem, Iterable) and not isinstance(elem, (str, bytes)):
            yield from _flatten(elem)
        else:
            yield elem


def _process_input(args):
    """Process an input argument, globbing files and directories."""
    for arg in _flatten([glob.glob(file) for file in args]):
        if os.path.exists(arg):
            if os.path.isfile(arg):
                yield arg
            elif os.path.isdir(arg):
                directory = os.walk(arg)
                for adir in directory:
                    base_dir = adir[0]
                    for filename in adir[2]:
                        yield os.path.join(base_dir, filename)
            else:
                _logger.warning(f'"{arg}" neither a file nor a directory, '
                                'skipping.')
        else:
            _logger.warning(f'"{arg}" not found, skipping.')


# PUBLIC FUNCTIONS
def get_user_config_directory(create_if_missing=True):
    """Return the path to the configuration directory.

    Optionally creates the directory if missing.
    """
    home_dir = os.environ[
        'USERPROFILE' if platform.system() == 'Windows' else 'HOME'
    ]
    config_dir = os.path.join(home_dir, '.pscodeanalyzer')
    if create_if_missing:
        os.makedirs(config_dir, exist_ok=True)
    return config_dir


def analyze(source_files, config_file, profile='default', substitutions=None,
            exhaustive=True, verbose_output=False):
    """Analyze the source code in the specified source files.

    The source_files argument must be a list whose items are either:
    - strings representing paths to files
    - two-item tuples whose first item is a string representing the path
      to a file and the second item is an integer denoting the type of
      the source file (can be None, in which case it is ignored)
    - three-item tuples whose first item is a string representing the
      path to a file, the second item is an integer denoting the type of
      the source file (can be None, in which case it is ignored), and
      the third item is a list of two-item tuples denoting intervals
      within which to limit the analysis

    Returns a list of FileReports objects.
    """
    global _verbose
    _verbose = verbose_output
    evaluators = []
    if source_files:
        _load_config(config_file, profile, substitutions)
        if _config_evaluators:
            for config in _config_evaluators:
                evaluators.append(_create_evaluator(config))
    if evaluators:
        file_reports = []
        for src in source_files:
            intervals = None
            if type(src) is str:
                file_path = src
                source_type = None
            else:
                file_path = src[0]
                source_type = src[1]
                if len(src) > 2:
                    intervals = src[2]
            reports = []
            for ev in evaluators:
                if intervals:
                    for iv in intervals:
                        ev.add_interval(iv[0], iv[1])
                if ev.is_proxy:
                    ev.attach(file_path, source_type=source_type)
                else:
                    if ev.applies_to_source_type(source_type):
                        ev.reset()
                    else:
                        _logger.debug(
                            f'- Evaluator: {ev.__class__.__name__} (not '
                            f'applicable for source type {str(source_type)})')
                        continue
                ev_rep = ev.evaluate(file_path)
                _logger.debug(f'- Evaluator: {ev.__class__.__name__} '
                              f'({str(len(ev_rep))} report(s))')
                reports.extend(ev_rep)
            if reports:
                fr = FileReports(file_path, source_type=source_type,
                                 reports=reports)
                file_reports.append(fr)
                status = fr.cumulative_status
                _print_verbose(fr)
                if not exhaustive and status == ReportType.ERROR:
                    break
            # else:
            #     _print_verbose(f'{os.path.basename(file_path)}: no reports')
        return file_reports
    else:
        print(f'No rules to evaluate in profile "{profile}" of configuration '
              f'file "{config_file}"', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    assert sys.version_info >= (3, 6), \
           'Python 3.6+ is required to run this script'
    default_config_file_path = os.path.join(get_user_config_directory(),
                                            default_config_file_name)
    parser = argparse.ArgumentParser(
        prog='pscodeanalyzer.engine',
        description='Performs static code analysis on source files.')
    parser.add_argument(
        '-v', '--verbosity', action='count', default=0,
        help='increase output verbosity')
    parser.add_argument(
        '-c', '--configfile', default=default_config_file_path,
        help=('the configuration file to use (defaults to '
              f'{default_config_file_path})'))
    parser.add_argument(
        '-p', '--profile', default='default',
        help=('the profile to use within the configuration file (defaults to '
              '"default")'))
    parser.add_argument(
        '-s', '--substitute', metavar='"VARIABLE=value"', action='append',
        help=('specify a variable substitution for the configuration profile '
              '(can be specified multiple times)'))
    parser.add_argument(
        'files', metavar='file_or_dir', nargs='+',
        help=('one or more source files or directories to process recursively '
              '(wildcards accepted)'))
    args = parser.parse_args()
    if args.verbosity == 2:
        logging.basicConfig(level=logging.INFO)
    elif args.verbosity > 2:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig()
    if args.substitute:
        substitutions = {}
        for s in args.substitute:
            # Remove leading spaces
            sub = s.lstrip()
            # Ignore empty substitutions
            if sub:
                parts = sub.split(sep='=', maxsplit=1)
                if parts[0]:
                    substitutions[parts[0]] = '' if len(parts) == 1 \
                                              else parts[1]
                else:
                    parser.error(f'Invalid substitution: "{s}"')
        if len(substitutions) == 0:
            substitutions = None
        else:
            _logger.info(f'substitutions = {substitutions}')
    else:
        substitutions = None
    file_reports = analyze(list(_process_input(args.files)), args.configfile,
                           profile=args.profile, substitutions=substitutions,
                           verbose_output=(args.verbosity > 0))
    for fr in file_reports:
        if fr.is_error:
            sys.exit(1)
