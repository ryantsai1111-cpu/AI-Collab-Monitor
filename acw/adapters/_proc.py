"""Shared helpers for launching adapter child processes without a console window."""
from __future__ import annotations

import subprocess


class CancellationOwnershipChanged(RuntimeError):
    """The operation being cancelled changed owner before the interrupt was dispatched."""


def hidden_flags():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _options(env, kwargs):
    kwargs.setdefault('creationflags', hidden_flags())
    if env is not None:
        kwargs['env'] = env
    return kwargs


def popen_hidden(argv, env=None, **kwargs):
    return subprocess.Popen(argv, **_options(env, kwargs))


def run_hidden(argv, env=None, **kwargs):
    return subprocess.run(argv, **_options(env, kwargs))
