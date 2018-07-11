# Copyright 2004-2005 Elemental Security, Inc. All Rights Reserved.
# Licensed to PSF under a Contributor Agreement.

# Modifications:
# Copyright 2014 David Halter. Integration into Jedi.
# Modifications are dual-licensed: MIT and PSF.

"""
Parser engine for the grammar tables generated by pgen.

The grammar table must be loaded first.

See Parser/parser.c in the Python distribution for additional info on
how this parsing engine works.
"""

from parso.python import tokenize


class InternalParseError(Exception):
    """
    Exception to signal the parser is stuck and error recovery didn't help.
    Basically this shouldn't happen. It's a sign that something is really
    wrong.
    """

    def __init__(self, msg, type, value, start_pos):
        Exception.__init__(self, "%s: type=%r, value=%r, start_pos=%r" %
                           (msg, tokenize.tok_name[type], value, start_pos))
        self.msg = msg
        self.type = type
        self.value = value
        self.start_pos = start_pos


class Stack(list):
    def get_tos_nodes(self):
        tos = self[-1]
        return tos[2][1]


def token_to_ilabel(grammar, type_, value):
    # Map from token to label
    if type_ == tokenize.NAME:
        # Check for reserved words (keywords)
        try:
            return grammar.keywords[value]
        except KeyError:
            pass

    try:
        return grammar.tokens[type_]
    except KeyError:
        return None


class PgenParser(object):
    """Parser engine.

    The proper usage sequence is:

    p = Parser(grammar, [converter])  # create instance
    p.setup([start])                  # prepare for parsing
    <for each input token>:
        if p.add_token(...):           # parse a token
            break
    root = p.rootnode                 # root of abstract syntax tree

    A Parser instance may be reused by calling setup() repeatedly.

    A Parser instance contains state pertaining to the current token
    sequence, and should not be used concurrently by different threads
    to parse separate token sequences.

    See driver.py for how to get input tokens by tokenizing a file or
    string.

    Parsing is complete when add_token() returns True; the root of the
    abstract syntax tree can then be retrieved from the rootnode
    instance variable.  When a syntax error occurs, error_recovery()
    is called. There is no error recovery; the parser cannot be used
    after a syntax error was reported (but it can be reinitialized by
    calling setup()).

    """

    def __init__(self, grammar, convert_node, convert_leaf, error_recovery, start):
        """Constructor.

        The grammar argument is a grammar.Grammar instance; see the
        grammar module for more information.

        The parser is not ready yet for parsing; you must call the
        setup() method to get it started.

        The optional convert argument is a function mapping concrete
        syntax tree nodes to abstract syntax tree nodes.  If not
        given, no conversion is done and the syntax tree produced is
        the concrete syntax tree.  If given, it must be a function of
        two arguments, the first being the grammar (a grammar.Grammar
        instance), and the second being the concrete syntax tree node
        to be converted.  The syntax tree is converted from the bottom
        up.

        A concrete syntax tree node is a (type, nodes) tuple, where
        type is the node type (a token or symbol number) and nodes
        is a list of children for symbols, and None for tokens.

        An abstract syntax tree node may be anything; this is entirely
        up to the converter function.

        """
        self.grammar = grammar
        self.convert_node = convert_node
        self.convert_leaf = convert_leaf

        # Each stack entry is a tuple: (dfa, state, node).
        # A node is a tuple: (type, children),
        # where children is a list of nodes or None
        newnode = (start, [])
        stackentry = (self.grammar.dfas[start], 0, newnode)
        self.stack = Stack([stackentry])
        self.rootnode = None
        self.error_recovery = error_recovery

    def parse(self, tokens):
        for type_, value, start_pos, prefix in tokens:
            if self.add_token(type_, value, start_pos, prefix):
                break
        else:
            # We never broke out -- EOF is too soon -- Unfinished statement.
            # However, the error recovery might have added the token again, if
            # the stack is empty, we're fine.
            if self.stack:
                raise InternalParseError("incomplete input", type_, value, start_pos)
        return self.rootnode

    def add_token(self, type_, value, start_pos, prefix):
        """Add a token; return True if this is the end of the program."""
        ilabel = token_to_ilabel(self.grammar, type_, value)

        # Loop until the token is shifted; may raise exceptions
        _gram = self.grammar
        _labels = _gram.labels
        _push = self._push
        _pop = self._pop
        _shift = self._shift
        while True:
            dfa, state, node = self.stack[-1]
            states, first = dfa
            arcs = states[state]
            # Look for a state with this label
            for i, newstate in arcs:
                t, v = _labels[i]
                if ilabel == i:
                    # Look it up in the list of labels
                    assert t < 256
                    # Shift a token; we're done with it
                    _shift(type_, value, newstate, prefix, start_pos)
                    # Pop while we are in an accept-only state
                    state = newstate
                    while states[state] == [(0, state)]:
                        _pop()
                        if not self.stack:
                            # Done parsing!
                            return True
                        dfa, state, node = self.stack[-1]
                        states, first = dfa
                    # Done with this token
                    return False
                elif t >= 256:
                    # See if it's a symbol and if we're in its first set
                    itsdfa = _gram.dfas[t]
                    itsstates, itsfirst = itsdfa
                    if ilabel in itsfirst:
                        # Push a symbol
                        _push(t, itsdfa, newstate)
                        break  # To continue the outer while loop
            else:
                if (0, state) in arcs:
                    # An accepting state, pop it and try something else
                    _pop()
                    if not self.stack:
                        # Done parsing, but another token is input
                        raise InternalParseError("too much input", type_, value, start_pos)
                else:
                    self.error_recovery(self.grammar, self.stack, arcs, type_,
                                        value, start_pos, prefix, self.add_token)
                    break

    def _shift(self, type_, value, newstate, prefix, start_pos):
        """Shift a token.  (Internal)"""
        dfa, state, node = self.stack[-1]
        newnode = self.convert_leaf(self.grammar, type_, value, prefix, start_pos)
        node[-1].append(newnode)
        self.stack[-1] = (dfa, newstate, node)

    def _push(self, type_, newdfa, newstate):
        """Push a nonterminal.  (Internal)"""
        dfa, state, node = self.stack[-1]
        newnode = (type_, [])
        self.stack[-1] = (dfa, newstate, node)
        self.stack.append((newdfa, 0, newnode))

    def _pop(self):
        """Pop a nonterminal.  (Internal)"""
        popdfa, popstate, (type_, children) = self.stack.pop()
        # If there's exactly one child, return that child instead of creating a
        # new node.  We still create expr_stmt and file_input though, because a
        # lot of Jedi depends on its logic.
        if len(children) == 1:
            newnode = children[0]
        else:
            newnode = self.convert_node(self.grammar, type_, children)

        try:
            # Equal to:
            # dfa, state, node = self.stack[-1]
            # symbol, children = node
            self.stack[-1][2][1].append(newnode)
        except IndexError:
            # Stack is empty, set the rootnode.
            self.rootnode = newnode
