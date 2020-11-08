import os
import sys
import click
import math
import functools

from types import FunctionType, MethodType
from click import echo
from datetime import datetime, timezone
from tabulate import tabulate
from dateutil.parser import isoparse


class ClickMixin:
    '''Base class that allows methods to work with click module
    '''
    def __init__(self):
        for attributename in dir(self):
            attribute = getattr(self, attributename)

            if isinstance(attribute, click.Command):
                attribute.callback = MethodType(attribute.callback, self)

                # Handle Group-like members
                for command in getattr(attribute, 'commands', {}).values():
                    command.callback = MethodType(command.callback, self)


class ObjectiveGroup(click.Group):
    def command(self, *args, **kwargs):
        '''The same as :func:`click.Group.command` but can
        return original function with `replacement=False` parameter
        '''
        superclass = super()
        
        def decorator(f):
            replacement = kwargs.pop('replacement', True)
            cmd = superclass.command(*args, **kwargs)(f)
            return cmd if replacement else f

        return decorator


def programdir(*p):
    '''Return absolute path to the program's directory with joining *p.
    '''
    dirpath = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(dirpath, *p)


def sizesuffix(size, suffixes=('B', 'KB', 'MB', 'GB', 'TB')):
    '''Convert size in bytes to human-readable representation.
    '''
    if size:
        i = int(math.log(size, 1024))
        s = size / (1024 ** int(math.log(size, 1024)))

        return '%s%s' % (round(s, 2), suffixes[i])

    return '0' + suffixes[0]


def strdate(t=None, fmt='%Y-%m-%d %H:%M:%S', tolocal=True):
    '''
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
