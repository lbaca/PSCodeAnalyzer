"""Module for sample test rules."""

from pscodeanalyzer.engine import Report, Rule
from pscodeanalyzer.rules.peoplecode import PeopleCodeParserListenerRule
from peoplecodeparser.PeopleCodeParser import PeopleCodeParser


class LineLengthRule(Rule):
    """Rule to enforce maximum line lengths.

    The following configuration options apply:
    - "max_length": an integer indicating the maximum acceptable line
      length
    """

    def __init__(self, config):
        """Construct a rule with the given configuration."""
        super(LineLengthRule, self).__init__(config)
        self.max_length = int(config.get('max_length'))
        if self.max_length <= 0:
            raise ValueError('max_length must be a positive integer')

    def evaluate_file(self, source_file):
        """Evaluate the rule against the provided file-like object.

        The file must already be open.

        Returns a list of Report objects.
        """
        reports = []
        for line, text in enumerate(source_file, start=1):
            if self.is_position_in_intervals(line):
                line_length = len(text)
                if line_length > self.max_length:
                    report = Report(
                        self.code, self.default_message,
                        report_type=self.default_report_type, line=line,
                        text=text,
                        detail=f'Line {line} has a length of {line_length}.')
                    reports.append(report)
        return reports


class LocalVariableNamingRule(PeopleCodeParserListenerRule):
    """Rule to enforce locally-defined variable naming convention.

    The following configuration options apply:
    - "variable_prefix": the prefix with which all locally-defined
      variables must begin
    """

    def __init__(self, config):
        """Initialize the rule."""
        super(LocalVariableNamingRule, self).__init__(config)
        self.variable_prefix = config.get('variable_prefix')
        if not self.variable_prefix:
            raise ValueError('empty variable_prefix is not allowed')

    def _process_single_variable(self, user_variable):
        """Verify if an individual variable name is compliant."""
        if user_variable:
            var_name = user_variable.getText()
            if not var_name.startswith(self.variable_prefix):
                line = user_variable.parentCtx.start.line
                column = user_variable.getSymbol().column + 1
                message = (f'Variable name "{var_name}" does not start with '
                           f'"{self.variable_prefix}"')
                report = Report(
                    self.code, message, line=line, column=column,
                    text=var_name,
                    detail=('The variable name does not begin with the prefix '
                            f'"{self.variable_prefix}".'))
                self.reports.append(report)

    def _verify_user_variables(self, ctx):
        """Verify if variable names are compliant.

        The local variable definition parser rule contains a list of
        USER_VARIABLE tokens, whereas the local variable declaration and
        assignment parser rule contains a single one.
        """
        line = ctx.start.line
        if self.is_position_in_intervals(line):
            user_variable = ctx.USER_VARIABLE()
            if type(user_variable) is list:
                for uv in user_variable:
                    self._process_single_variable(uv)
            else:
                self._process_single_variable(user_variable)

    # Enter a parse tree produced by
    # PeopleCodeParser#localVariableDefinition.
    def enterLocalVariableDefinition(
            self, ctx: PeopleCodeParser.LocalVariableDefinitionContext):
        """Event triggered when a local variable definition is found.

        Local variable definitions are of the following forms:

            Local string &var1;
            Local number &var2, &var3, &var4;
        """
        self._verify_user_variables(ctx)

    # Enter a parse tree produced by
    # PeopleCodeParser#localVariableDeclAssignment.
    def enterLocalVariableDeclAssignment(
            self, ctx: PeopleCodeParser.LocalVariableDeclAssignmentContext):
        """Event triggered for local variable definition-assignments.

        These are of the form:

            Local string &var5 = "Some value";
            Local number &var6 = (&var2 + &var3) * &var4;
        """
        self._verify_user_variables(ctx)
