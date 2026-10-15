"""Optional timing hooks used by column generation builders and solvers."""

from contextlib import contextmanager


@contextmanager
def timed_component(progress, name, *, pricing_stage=None):
    """Time a component only for progress reporters with explicit support.

    Plain queues and mocks preserve their existing reporting behavior. The
    reporter decides whether a component is active so nested or unrelated
    phases can decline timing without requiring different solver interfaces.
    """
    active = False
    if getattr(progress, "supports_cg_timing", False) is True:
        active = (progress.start_component(name) if pricing_stage is None else
                  progress.start_component(name, pricing_stage=pricing_stage))
    try:
        yield
    finally:
        if active:
            progress.end_component(name)
