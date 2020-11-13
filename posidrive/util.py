import os
import sys
import click
import math
import functools

from types import FunctionType, MethodType
from click import echo
from click.exceptions import ClickException
from click.exceptions import Exit as ClickExit
from datetime import datetime, timezone
from dateutil.parser import isoparse


class ObjectiveGroup(click.Group):
    def bind_class_instance(self, instance):
        for command in self.commands.values():
            command.callback = MethodType(command.callback, instance)

        self.exception_handler_callback = \
            MethodType(self.exception_handler_callback, instance)

        self.callback = MethodType(self.callback, instance)

    def command(self, *args, **kwargs):
        '''The same as :func:`click.Group.command` but can
        return original function with `replacement=False` parameter
        '''
        superclass = super()
        replacement = kwargs.pop('replacement', True)

        def decorator(f):
            cmd = superclass.command(*args, **kwargs)(f)
            return cmd if replacement else f

        return decorator

    def list_commands(self, ctx):
        return list(self.commands)

    def exception_handler(self, ignore=None):
        '''Register a function to handle exceptions in subcommands.
        If handler returns None, re-raise exception.
        '''
        def decorator(f):
            if ignore is not None:
                self.exception_handler_ignore = ignore

            self.exception_handler_callback = f
            return f

        return decorator

    exception_handler_callback = lambda *args: None
    exception_handler_ignore = (ClickException, ClickExit)

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except self.exception_handler_ignore:
            raise
        except Exception as e:
            value = self.exception_handler_callback(ctx, e)

            if value is None:
                raise

            return value

def programdir(*p):
    '''Return absolute path to the program's directory with joining *p.
    '''
    dirpath = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(dirpath, *p)


def pathtosave(filename, path=None):
    '''Return path to save file.
    If `path` is directory, join it `filename`. Ignore `filename` otherwise.
    '''
    if path:
        if os.path.isdir(path):
            return os.path.join(path, filename)
        else:
            return path
    else:
        return filename


def sizesuffix(size, suffixes=('B', 'K', 'M', 'G', 'T')):
    '''Convert size in bytes to human-readable representation.
    '''
    size = int(size)

    if size:
        index = int(math.log(size, 1024))
        value = size / (1024 ** index)
        return f'{value:.1f}'.rstrip('0').rstrip('.') + suffixes[index]

    return '0' + suffixes[0]


def strdate(t=None, fmt='%Y-%m-%d %H:%M:%S', tolocal=True):
    '''Format `t` parameter to string representation.

    :param t: Time. May be None, str or datetime.
    :param fmt: Style string. See time.strftime call.
    :param tolocal: If True, convert UTC date to local time.
    '''
    if t is None:
        d = datetime.utcnow()
    elif isinstance(t, str):
        d = isoparse(t)
    else:
        d = t

    if tolocal:
        d = d.replace(tzinfo=timezone.utc).astimezone(tz=None)

    return d.strftime(fmt)


# Like max(), but compares by length
maxlen = functools.partial(max, key=len)


def table(rows, colstransform={}):
    '''Make aligned table

    :param rows: Iterable with rows
    :param colstransform: Mapping in form {ncol: callable(str, align)},
                          e. g. table(rows, colstransform={0: str.rjust})
    '''
    colsalign = tuple(map(len, map(maxlen, *rows)))

    def line(row):
        for i, (cell, align) in enumerate(zip(row, colsalign)):
            yield colstransform.get(i, str.ljust)(cell, align)

    return '\n'.join(' '.join(line(i)).rstrip() for i in rows)
