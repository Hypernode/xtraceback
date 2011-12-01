import functools
import inspect
import os
import pprint
import struct
import warnings

try:
    import fcntl
except ImportError:
    fcntl = None
else:
    import termios

try:
    import pygments
except ImportError:
    pygments = None
else:
    from pygments.formatters.terminal import TerminalFormatter
    from .lexer import PythonXTracebackLexer

from .xtracebackframe import XTracebackFrame


class XTracebackOptions(object):
    """
    XTraceback options

    :ivar stream: A file-like object that is the default for print_* methods
    :type stream: file
    :ivar color: Flag to force color on or off - if None look to whether the
        `stream` is a tty
    :type color: bool
    :ivar print_width: How many columns wide to print the screen - if None and
        `stream` is a tty on Unix then fill the available width
    """

    # default options
    _options = dict(
        stream=None,
        color=None,
        print_width=None,
        offset=0,
        limit=None,
        context=5,
        globals_module_include=None,
        )

    # default flags
    _flags = dict(
        show_args=True,
        show_locals=True,
        show_globals=False,
        qualify_methods=True,
        shorten_filenames=True,
        )

    def __init__(self, options):
        # options
        for key in self._options:
            value = options.pop(key, None)
            if value is None:
                value = self._options[key]
            setattr(self, key, value)
        # flags
        for key in self._flags:
            value = options.pop(key, None)
            if value is None:
                value = self._flags[key]
            else:
                value = bool(value)
            setattr(self, key, value)
        # there should be no more options
        if options:
            raise TypeError("Unsupported options: %r" % options)


class XTraceback(object):
    """
    An extended traceback formatter

    """

    DEFAULT_WIDTH = 80

    REFORMAT = {
        dict: ("{", "}"),
        list: ("[", "]"),
        tuple: ("(", ")"),
        set: ("set([", "])"),
        frozenset: ("frozenset([", "])"),
        }

    _stdlib_path = os.path.dirname(os.path.realpath(inspect.getsourcefile(os)))


    def __init__(self, etype, value, tb, **options):
        """
        :param etype: The exception type
        :type etype: type
        :param value: The exception instance
        :type value: Exception
        :param tb: The traceback instance
        :type tb: traceback
        :param options: Options for this instance
        :type options: dict
        """

        self.etype = etype
        self.value = value

        self.options = XTracebackOptions(options)

        # placeholders
        self._lexer = None
        self._formatter = None

        # keep track of objects we've seen
        self.seen = {}

        # get the traceback frames and work out number padding
        self.tb_frames = []
        self.number_padding = 0
        i = 0
        while tb is not None and (self.options.limit is None
                                  or i < self.options.limit):
            if i >= self.options.offset:
                frame_info = inspect.getframeinfo(tb, self.options.context)
                frame = XTracebackFrame(self, tb.tb_frame, frame_info, i)
                if not frame.exclude:
                    self.tb_frames.append(frame)
                    self.number_padding = max(len(str(frame_info[1])),
                                              self.number_padding)
            tb = tb.tb_next
            i += 1

        # get rid of tb once we no longer need it
        tb = None

    @property
    def tty_stream(self):
        """
        Whether or not our stream is a tty
        """
        return hasattr(self.options.stream, "isatty") \
            and self.options.stream.isatty()

    @property
    def color(self):
        """
        Whether or not color should be output
        """
        return self.tty_stream if self.options.color is None \
            else self.options.color

    @property
    def print_width(self):
        """
        Width of one screen
        """
        print_width = self.options.print_width
        if print_width is None \
            and fcntl is not None \
            and self.tty_stream:
            print_width = struct.unpack(
                'HHHH',
                fcntl.ioctl(self.options.stream,
                            termios.TIOCGWINSZ,
                            struct.pack('HHHH', 0, 0, 0, 0)),
                )[1]
        else:
            print_width = self.DEFAULT_WIDTH
        return print_width

    def __str__(self):
        return self._str_lines(self._format_exception())

    def _format_filename(self, filename):
        if self.options.shorten_filenames:
            filename = os.path.realpath(filename)
            if filename.startswith(self._stdlib_path):
                filename = filename.replace(self._stdlib_path, "<stdlib>")
            elif hasattr(os.path, "relpath"):
                # os.path.relpath was introduced in python 2.5
                relative = os.path.relpath(filename)
                if len(relative) < len(filename):
                    filename = relative
        # using str on filename to make Jython (default string is unicode)
        # consistent with CPython
        return str(filename)

    def _format_variable(self, key, value, indent=4, prefix="",
                         separator=" = "):
        base_size = indent + len(prefix) + len(key) + len(separator)
        if isinstance(value, basestring) and len(value) > self.print_width * 2:
            # truncate long strings - minus 2 for the quotes and 3 for
            # the ellipsis
            value = value[:self.print_width - base_size - 2 - 3] + "..."
        vtype = type(value)
        try:
            pvalue = pprint.pformat(value, indent=0)
        except:
            pvalue = "<unprintable %s object>" % vtype.__name__
        if base_size + len(pvalue) > self.print_width:
            reformat = self.REFORMAT.get(vtype)
            if reformat is not None:
                start, end = reformat
                lines = map(str.strip,
                            pvalue.lstrip(start).rstrip(end).splitlines())
                sub_indent = "\n" + " " * (indent + 4)
                pvalue = "".join((start, sub_indent, sub_indent.join(lines),
                                  ",", sub_indent, end))
        return "".join((" " * indent, prefix, key, separator, pvalue))

    # { Line formatting

    def _highlight(self, string):
        if pygments is None:
            warnings.warn("highlighting not available - pygments is required")
        else:
            if self._lexer is None:
                self._lexer = PythonXTracebackLexer()
            if self._formatter is None:
                try:
                    self._formatter = TerminalFormatter()
                except pygments.util.ClassNotFound, exc:
                    warnings.warn("highlighting not available - %s" % exc)
                    # this can happen when running under gae
                    return string
            try:
                return pygments.highlight(string, self._lexer, self._formatter)
            except KeyboardInterrupt:
                # let the user abort highlighting if problematic
                pass
        return string

    def _str_lines(self, lines):
        exc_str = "".join(lines)
        if self.color:
            exc_str = self._highlight(exc_str)
        return exc_str

    def _format_lines(self, lines):
        return map(self._highlight, lines) if self.color else lines

    def _print_lines(self, lines):
        if self.options.stream is None:
            raise RuntimeError("Cannot print - %r has None stream" % self)
        self.options.stream.write(self._str_lines(lines))

    # { Traceback format - these return lines that should be joined with ""

    def _format_tb(self):
        return ["%s\n" % frame for frame in self.tb_frames]

    def _format_exception_only(self):

        lines = []

        try:
            value_str = str(self.value)
        except Exception:
            try:
                value_str = unicode(self.value).encode("ascii",
                                                       "backslashreplace")
            except Exception:
                value_str = "<unprintable %s object>" \
                                % type(self.value).__name__

        if isinstance(self.value, SyntaxError):
            # taken from traceback.format_exception_only
            try:
                msg, (filename, lineno, offset, badline) = self.value.args
            except:
                pass
            else:
                filename = filename and self._format_filename(filename) \
                               or "<string>"
                filename = filename or "<string>"
                lines.append('  File "%s", line %d\n' % (filename, lineno))
                if badline is not None:
                    lines.append('    %s\n' % badline.strip())
                    if offset is not None:
                        caretspace = badline.rstrip('\n')[:offset].lstrip()
                        # non-space whitespace (likes tabs) must be kept for
                        # alignment
                        caretspace = ((c.isspace() and c or ' ')
                                      for c in caretspace)
                        # only three spaces to account for offset1 == pos 0
                        lines.append('   %s^\n' % ''.join(caretspace))
                    value_str = msg

        exc_line = isinstance(self.etype, type) and self.etype.__name__ \
                       or str(self.etype)
        if self.value is not None and value_str:
            exc_line += ": %s" % value_str
        lines.append(exc_line + "\n")

        return lines

    def _format_exception(self):
        lines = list(self._format_tb())
        if lines:
            lines.insert(0, "Traceback (most recent call last):\n")
        lines.extend(self._format_exception_only())
        return lines

    # { Interface - this is compatible with the stdlib's traceback module

    def format_tb(self):
        return self._format_lines(self._format_tb())

    def format_exception_only(self):
        return self._format_lines(self._format_exception_only())

    def format_exception(self):
        return self._format_lines(self._format_exception())

    def print_tb(self):
        self._print_lines(self._format_tb())

    def print_exception(self):
        self._print_lines(self._format_exception())

    # }
