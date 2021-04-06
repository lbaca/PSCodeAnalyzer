"""Static code analyzer rules for PeopleCode."""

import logging
from abc import ABC
from collections import OrderedDict

from antlr4 import CommonTokenStream, FileStream, ParseTreeWalker
from antlr4.error.ErrorListener import ErrorListener

from peoplecodeparser.PeopleCodeLexer import PeopleCodeLexer
from peoplecodeparser.PeopleCodeParser import PeopleCodeParser
from peoplecodeparser.PeopleCodeParserListener import PeopleCodeParserListener

from ..engine import Proxy, Report, Rule


# GLOBAL VARIABLES
_logger = logging.getLogger('peoplecode')


# PARSER INFRASTRUCTURE CLASSES
class ReportingErrorListener(ErrorListener):
    """An error listener for the PeopleCode parser.

    It outputs errors as Report objects.
    """

    def __init__(self, reports):
        """Initialize the error listener."""
        super(ReportingErrorListener, self).__init__()
        self.reports = reports

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        """Handle a syntax error."""
        _logger.debug(f'Syntax error at {line},{column + 1}: {msg}')
        report = Report('PeopleCodeParser', msg, line=line,
                        column=(column + 1))
        self.reports.append(report)


# PROXIES
class PeopleCodeParserProxy(Proxy):
    """Proxy class for rules that require the PeopleCode parser.

    It will handle the parsing optimally to avoid parsing the same file
    multiple times. It will assume that all evaluators that are not
    themselves proxies will be subclasses of
    PeopleCodeParserListenerRule.

    The following configuration options apply:
    - "encoding": the encoding with which to open the source files
      (optional, defaults to "utf-8")
    """

    def __init__(self, config):
        """Construct a PeopleCode parser proxy.

        Initialization will be lazy.
        """
        super(PeopleCodeParserProxy, self).__init__(config)
        self.encoding = config.get('encoding', 'utf-8')

    def reset(self):
        """Reset the proxy for a new source."""
        super(PeopleCodeParserProxy, self).reset()
        self.parse_reports = []
        self.starting_rule = 'appClass' if self.source_type == 58 \
            or (self.source_type is None
                and self.file_path
                and '058-' in self.file_path) else 'program'
        self._file_stream = None
        self._lexer = None
        self._token_stream = None
        self._parser = None
        self._parse_tree = None
        self._walker = None

    @property
    def file_stream(self):
        """Lazy initialization of file_stream."""
        if self._file_stream is None:
            self._file_stream = FileStream(self.file_path,
                                           encoding=self.encoding)
        return self._file_stream

    @property
    def lexer(self):
        """Lazy initialization of lexer."""
        if self._lexer is None:
            self._lexer = PeopleCodeLexer(self.file_stream)
        return self._lexer

    @property
    def token_stream(self):
        """Lazy initialization of token_stream."""
        if self._token_stream is None:
            self._token_stream = CommonTokenStream(self.lexer)
        return self._token_stream

    @property
    def parser(self):
        """Lazy initialization of parser."""
        if self._parser is None:
            self._parser = PeopleCodeParser(self.token_stream)
        self._parser.removeErrorListeners()
        self.parse_reports = []
        listener = ReportingErrorListener(self.parse_reports)
        self._parser.addErrorListener(listener)
        return self._parser

    @property
    def parse_tree(self):
        """Lazy initialization of parse_tree."""
        if self._parse_tree is None:
            _logger.info(f'{self.__class__.__name__}:Parsing file '
                         f'"{self.file_path}"...')
            self._parse_tree = getattr(self.parser, self.starting_rule)()
            _logger.info(f'{self.__class__.__name__}:Parsing complete')
        return self._parse_tree

    @property
    def walker(self):
        """Lazy initialization of walker."""
        if self._walker is None:
            self._walker = ParseTreeWalker()
        return self._walker

    def _propagate_state(self, previous_ev, current_ev):
        """Copy the annotations between subsequent evaluators."""
        if (isinstance(previous_ev, PeopleCodeParserListenerRule)
                and isinstance(current_ev, PeopleCodeParserListenerRule)):
            if current_ev.inherit_annotations:
                current_ev.annotations = previous_ev.annotations

    def _evaluate_rule(self, rule):
        """Evaluate a rule, returning its reports."""
        tree = self.parse_tree
        walker = self.walker
        try:
            walker.walk(rule, tree)
            return rule.evaluate()
        except NotApplicableError as e:
            _logger.debug(f'{self.__class__.__name__}:{str(e)}')
            return []

    def evaluate(self, exhaustive=False):
        """Extend the superclass's evaluation results with any errors."""
        _logger.debug(f'Evaluating {self.__class__.__name__}')
        super_reports = super(PeopleCodeParserProxy, self).evaluate(
            exhaustive=exhaustive)
        all_reports = self.parse_reports + super_reports
        return all_reports


# RULES
class PeopleCodeParserListenerRule(Rule, PeopleCodeParserListener):
    """Base class for rules that are PeopleCodeParserListener instances.

    The following configuration options apply:
    - "inherit_annotations": indicates whether this rule should inherit
      the annotations from the rule that ran before it (optional,
      defaults to False)
    """

    def __init__(self, config):
        """Initialize the rule.

        The annotations dictionary can be used to map tree nodes to
        values. This facility be useful if one listener needs to
        annotate the tree for another downstream listener.
        """
        super(PeopleCodeParserListenerRule, self).__init__(config)
        self.annotations = {}
        self.inherit_annotations = config.get('inherit_annotations', False)

    def reset(self):
        """Reset the rule for a new evaluation."""
        super(PeopleCodeParserListenerRule, self).reset()
        self.reports = []

    def evaluate(self, source=None):
        """Return the list of Report objects generated by the rule."""
        _logger.debug(f'Evaluating {self.__class__.__name__}')
        return self.reports


class SQLExecRule(PeopleCodeParserListenerRule):
    """Rule to check for SQLExec calls with literal SQL statements."""

    def __init__(self, config):
        """Initialize the rule."""
        super(SQLExecRule, self).__init__(config)

    # Enter a parse tree produced by PeopleCodeParser#simpleFunctionCall.
    def enterSimpleFunctionCall(
            self, ctx: PeopleCodeParser.SimpleFunctionCallContext):
        """Event triggered when a simple function call is found."""
        line = ctx.start.line
        if self.is_position_in_intervals(line):
            function_name = ctx.genericID().allowableFunctionName()
            if function_name and function_name.getText().upper() == 'SQLEXEC':
                args = ctx.functionCallArguments()
                if args:
                    expr = args.expression(i=0)
                    if hasattr(expr, 'literal'):
                        message = 'SQLExec with literal first argument'
                    elif hasattr(expr, 'PIPE'):
                        message = 'SQLExec with concatenated first argument'
                    else:
                        message = None
                    if message:
                        report = Report(
                            self.code, message,
                            line=line, column=(ctx.start.column + 1),
                            text=ctx.getText(),
                            detail=('The first argument to SQLExec should be '
                                    'either a SQL object reference or a '
                                    'variable with dynamically generated '
                                    'SQL.'))
                        self.reports.append(report)
                else:
                    # Should never happen in valid PeopleCode
                    report = Report(
                        self.code, 'SQLExec with no arguments', line=line,
                        column=(ctx.start.column + 1), text=ctx.getText(),
                        detail=('SQLExec should not be called without '
                                'arguments.'))
                    self.reports.append(report)


# SYMBOL RESOLUTION CLASSES
class NotApplicableError(Exception):
    """An exception when a listener is not applicable to a given input.

    For example, if SymbolDefinitionPhaseRule were to be called for an
    Application Class, it would raise this exception.
    """

    pass


class SymbolDefinitionPhaseRule(PeopleCodeParserListenerRule):
    """A listener that defines symbols for later reference.

    It is suitable for testing for undeclared variables. As such, should
    never be used with Application Classes, where undeclared variables
    are forbidden by design.
    """

    def __init__(self, config):
        """Initialize the rule."""
        super(SymbolDefinitionPhaseRule, self).__init__(config)

    def _save_scope(self, ctx, scope):
        """Annotate the tree node with the scope."""
        self.annotations[ctx.start.tokenIndex] = scope

    def _define_variable(self, token):
        """Define a variable or argument in the current scope."""
        var = VariableSymbol(token.getText(), token.getSourceInterval()[0])
        self.current_scope.define(var)

    def _pop_scope(self):
        """Pop the scope."""
        self._log_current_scope()
        self.current_scope = self.current_scope.parent_scope

    def _log_current_scope(self):
        """Output the current scope (if not empty) to the logger."""
        if _logger.isEnabledFor(logging.DEBUG):
            if not self.current_scope.is_empty:
                _logger.debug(f'{self.__class__.__name__}:'
                              f'{str(self.current_scope)}')

    # Enter a parse tree produced by PeopleCodeParser#AppClassProgram.
    def enterAppClassProgram(
            self, ctx: PeopleCodeParser.AppClassProgramContext):
        """Raise an exception.

        Application Classes should not be subjected to this listener.
        """
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#AppClassProgram@{ctx.start.line},'
                      f'{ctx.start.column + 1}')
        raise NotApplicableError('This listener should not be used for '
                                 'Application Classes')

    # Enter a parse tree produced by PeopleCodeParser#InterfaceProgram.
    def enterInterfaceProgram(
            self, ctx: PeopleCodeParser.InterfaceProgramContext):
        """Raise an exception.

        Application Classes should not be subjected to this listener.
        """
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#InterfaceProgram@{ctx.start.line},'
                      f'{ctx.start.column + 1}')
        raise NotApplicableError('This listener should not be used for '
                                 'Application Classes')

    # Enter a parse tree produced by PeopleCodeParser#program.
    def enterProgram(self, ctx: PeopleCodeParser.ProgramContext):
        """Initialize the scoping mechanism."""
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#program@{ctx.start.line},{ctx.start.column + 1}')
        self.annotations = {}
        self.current_scope = GlobalScope()
        # Annotate the root node with the global scope for the
        # SymbolReferencePhaseRule
        self._save_scope(ctx, self.current_scope)

    # Enter a parse tree produced by PeopleCodeParser#functionDefinition.
    def enterFunctionDefinition(
            self, ctx: PeopleCodeParser.FunctionDefinitionContext):
        """Start a new function scope."""
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#functionDefinition@{ctx.start.line},'
                      f'{ctx.start.column + 1}')
        name = ctx.allowableFunctionName().getText()
        scope = FunctionScope(name, self.current_scope)
        self.current_scope = scope
        self._save_scope(ctx, scope)

    # Exit a parse tree produced by PeopleCodeParser#functionArgument.
    def exitFunctionArgument(
            self, ctx: PeopleCodeParser.FunctionArgumentContext):
        """Add a function argument to the current scope."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#functionArgument@{ctx.stop.line},'
                      f'{ctx.stop.column + 1}')
        self._define_variable(ctx.USER_VARIABLE())

    # Exit a parse tree produced by PeopleCodeParser#functionDefinition.
    def exitFunctionDefinition(
            self, ctx: PeopleCodeParser.FunctionDefinitionContext):
        """Pop the scope."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#functionDefinition@{ctx.stop.line},'
                      f'{ctx.stop.column + 1}')
        self._pop_scope()

    # Exit a parse tree produced by PeopleCodeParser#nonLocalVarDeclaration.
    def exitNonLocalVarDeclaration(
            self, ctx: PeopleCodeParser.NonLocalVarDeclarationContext):
        """Add global/component variables to the current scope.

        The current scope should be the global scope.
        """
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#nonLocalVarDeclaration@{ctx.stop.line},'
                      f'{ctx.stop.column + 1}')
        var_tokens = ctx.USER_VARIABLE()
        if var_tokens:
            for var in var_tokens:
                self._define_variable(var)

    # Exit a parse tree produced by PeopleCodeParser#localVariableDefinition.
    def exitLocalVariableDefinition(
            self, ctx: PeopleCodeParser.LocalVariableDefinitionContext):
        """Add local variables to the current scope."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#localVariableDefinition@{ctx.stop.line},'
                      f'{ctx.stop.column + 1}')
        var_tokens = ctx.USER_VARIABLE()
        if var_tokens:
            for var in var_tokens:
                self._define_variable(var)

    # Exit a parse tree produced by
    # PeopleCodeParser#localVariableDeclAssignment.
    def exitLocalVariableDeclAssignment(
            self, ctx: PeopleCodeParser.LocalVariableDeclAssignmentContext):
        """Add a local variable to the current scope."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#localVariableDeclAssignment@{ctx.stop.line},'
                      f'{ctx.stop.column + 1}')
        self._define_variable(ctx.USER_VARIABLE())

    # Exit a parse tree produced by PeopleCodeParser#constantDeclaration.
    def exitConstantDeclaration(
            self, ctx: PeopleCodeParser.ConstantDeclarationContext):
        """Add a constant to the current scope."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#constantDeclaration@{ctx.stop.line},'
                      f'{ctx.stop.column + 1}')
        self._define_variable(ctx.USER_VARIABLE())

    # Enter a parse tree produced by PeopleCodeParser#statementBlock.
    def enterStatementBlock(self, ctx: PeopleCodeParser.StatementBlockContext):
        """Push a new local scope into the stack."""
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#statementBlock@{ctx.start.line},'
                      f'{ctx.start.column + 1}')
        scope = LocalScope(f'local@{ctx.start.line},{ctx.start.column + 1}',
                           self.current_scope)
        self.current_scope = scope
        self._save_scope(ctx, scope)

    # Exit a parse tree produced by PeopleCodeParser#statementBlock.
    def exitStatementBlock(self, ctx: PeopleCodeParser.StatementBlockContext):
        """Pops the scope."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#statementBlock@{ctx.stop.line},{ctx.stop.column + 1}')
        self._pop_scope()

    # Exit a parse tree produced by PeopleCodeParser#program.
    def exitProgram(self, ctx: PeopleCodeParser.ProgramContext):
        """Signifies the end of the parse."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#program@{ctx.stop.line},{ctx.stop.column + 1}')
        self._log_current_scope()


class SymbolReferencePhaseRule(PeopleCodeParserListenerRule):
    """A listener that references symbols defined earlier.

    The symbols are stored in the annotations dictionary, to check for
    undeclared variables. It should never be used with Application
    Classes, where undeclared variables are forbidden by design.
    """

    def __init__(self, config):
        """Initialize the rule."""
        super(SymbolReferencePhaseRule, self).__init__(config)

    def _resolve_variable(self, token):
        """Resolve a variable defined earlier."""
        name = token.getText()
        token_symbol = token.getSymbol()
        line = token_symbol.line
        if self.is_position_in_intervals(line):
            symbol = self.current_scope.resolve(name)
            if symbol is None:
                # Symbol not found anywhere
                report = Report(
                    self.code, f'Undeclared variable {name}', line=line,
                    column=(token_symbol.column + 1), text=name,
                    detail=(f'{name} does not resolve to any variable, '
                            'constant or function argument in scope.'))
                self.reports.append(report)
            elif token_symbol.tokenIndex < symbol.index:
                # Symbol found, but it is defined after it is referenced
                report = Report(
                    self.code,
                    f'Variable {name} is referenced before it is declared',
                    line=line, column=(token_symbol.column + 1), text=name,
                    detail=(f'{name} is referenced before it is declared as a '
                            'variable, constant or function argument within '
                            'scope.'))
                self.reports.append(report)

    def _set_current_scope(self, ctx):
        """Set the current scope."""
        self.current_scope = self.annotations[ctx.start.tokenIndex]
        self._log_current_scope()

    def _pop_scope(self):
        """Pop the scope."""
        self.current_scope = self.current_scope.parent_scope
        self._log_current_scope()

    def _log_current_scope(self):
        """Output the current scope (if not empty) to the logger."""
        if _logger.isEnabledFor(logging.DEBUG):
            if not self.current_scope.is_empty:
                _logger.debug(f'{self.__class__.__name__}:'
                              f'{str(self.current_scope)}')

    # Enter a parse tree produced by PeopleCodeParser#AppClassProgram.
    def enterAppClassProgram(
            self, ctx: PeopleCodeParser.AppClassProgramContext):
        """Raise an exception.

        Application Classes should not be subjected to this listener.
        """
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#AppClassProgram@{ctx.start.line},'
                      f'{ctx.start.column + 1}')
        raise NotApplicableError('This listener should not be used for '
                                 'Application Classes')

    # Enter a parse tree produced by PeopleCodeParser#InterfaceProgram.
    def enterInterfaceProgram(
            self, ctx: PeopleCodeParser.InterfaceProgramContext):
        """Raise an exception.

        Application Classes should not be subjected to this listener.
        """
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#InterfaceProgram@{ctx.start.line},'
                      f'{ctx.start.column + 1}')
        raise NotApplicableError('This listener should not be used for '
                                 'Application Classes')

    # Enter a parse tree produced by PeopleCodeParser#program.
    def enterProgram(self, ctx: PeopleCodeParser.ProgramContext):
        """Set the global scope."""
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#program@{ctx.start.line},{ctx.start.column + 1}')
        self._set_current_scope(ctx)

    # Enter a parse tree produced by PeopleCodeParser#functionDefinition.
    def enterFunctionDefinition(
            self, ctx: PeopleCodeParser.FunctionDefinitionContext):
        """Set the function scope."""
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#functionDefinition@{ctx.start.line},'
                      f'{ctx.start.column + 1}')
        self._set_current_scope(ctx)

    # Exit a parse tree produced by PeopleCodeParser#functionDefinition.
    def exitFunctionDefinition(
            self, ctx: PeopleCodeParser.FunctionDefinitionContext):
        """Pop the scope."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#functionDefinition@{ctx.stop.line},'
                      f'{ctx.stop.column + 1}')
        self._pop_scope()

    # Enter a parse tree produced by PeopleCodeParser#statementBlock.
    def enterStatementBlock(self, ctx: PeopleCodeParser.StatementBlockContext):
        """Set the local scope."""
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#statementBlock@{ctx.start.line},'
                      f'{ctx.start.column + 1}')
        self._set_current_scope(ctx)

    # Exit a parse tree produced by PeopleCodeParser#statementBlock.
    def exitStatementBlock(self, ctx: PeopleCodeParser.StatementBlockContext):
        """Pop the scope."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#statementBlock@{ctx.stop.line},{ctx.stop.column + 1}')
        self._pop_scope()

    # Enter a parse tree produced by PeopleCodeParser#forStatement.
    def enterForStatement(self, ctx: PeopleCodeParser.ForStatementContext):
        """Event triggered when a For statement is encountered.

        The goal is to resolve its index variable.
        """
        _logger.debug(f'{self.__class__.__name__}:>>> '
                      f'#forStatement@{ctx.start.line},{ctx.start.column + 1}')
        self._resolve_variable(ctx.USER_VARIABLE())

    # Exit a parse tree produced by PeopleCodeParser#IdentUserVariable.
    def exitIdentUserVariable(
            self, ctx: PeopleCodeParser.IdentUserVariableContext):
        """Event triggered when a user variable is encountered."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#IdentUserVariable@{ctx.stop.line},'
                      f'{ctx.stop.column + 1}')
        self._resolve_variable(ctx.USER_VARIABLE())

    # Exit a parse tree produced by PeopleCodeParser#program.
    def exitProgram(self, ctx: PeopleCodeParser.ProgramContext):
        """Signify the end of the parse."""
        _logger.debug(f'{self.__class__.__name__}:<<< '
                      f'#program@{ctx.stop.line},{ctx.stop.column + 1}')


class Scope(ABC):
    """Abstract base class for scopes.

    There are no @abstractmethods defined, but this class should never
    be instantiated directly.
    """

    def __init__(self, name, parent_scope):
        """Initialize the scope.

        The symbols dictionary stores symbols keyed by their names.
        """
        self.name = name
        self.parent_scope = parent_scope
        self._symbols = {}

    def __str__(self):
        """Return a string representation of the scope."""
        return (f'{self.qualifier}: '
                f'{str([s.name for s in self.symbols.values()])}')

    def resolve(self, name):
        """Resolve a symbol by name."""
        search_name = name.lower()
        s = self.symbols.get(search_name)
        if s is None:
            # Not found in this scope; check parent scope recursively
            if self.parent_scope:
                s = self.parent_scope.resolve(search_name)
        return s

    def define(self, symbol):
        """Define a symbol in this scope."""
        symbol.scope = self
        self.symbols[symbol.name.lower()] = symbol

    @property
    def symbols(self):
        """Return the scope's symbols."""
        return self._symbols

    @property
    def qualifier(self):
        """Return the scope's qualifier."""
        if self.parent_scope:
            qual = f'{self.parent_scope.qualifier}.'
        else:
            qual = ''
        return f'{qual}{self.name}'

    @property
    def is_empty(self):
        """Return True if the scope defines no symbols."""
        return (len(self.symbols) == 0)


class GlobalScope(Scope):
    """The global scope."""

    def __init__(self):
        """Initialize the scope."""
        super(GlobalScope, self).__init__('global', None)


class LocalScope(Scope):
    """A local scope."""

    def __init__(self, name, parent_scope):
        """Initialize the scope."""
        super(LocalScope, self).__init__(name, parent_scope)


class Symbol:
    """Base class for symbols."""

    def __init__(self, name, index):
        """Initialize the symbol."""
        self.name = name
        self.index = index
        self.scope = None

    def __str__(self):
        """Return a string representation of the symbol."""
        return f'{self.name}@{self.index}'


class VariableSymbol(Symbol):
    """A symbol denoting a variable."""

    def __init__(self, name, index):
        """Initialize the symbol."""
        super(VariableSymbol, self).__init__(name, index)


class FunctionScope(Scope):
    """A scoped symbol representing a function."""

    def __init__(self, name, parent_scope):
        """Initialize the scoped symbol."""
        super(FunctionScope, self).__init__(name, parent_scope)
        self._arguments = OrderedDict()

    @property
    def symbols(self):
        """Return the scope's symbols."""
        return self._arguments
