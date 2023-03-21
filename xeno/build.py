# --------------------------------------------------------------------
# build.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Friday March 17, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

from typing import Optional, cast

# --------------------------------------------------------------------
from xeno.async_injector import AsyncInjector
from xeno.attributes import MethodAttributes
from xeno.recipe import Recipe, Lambda
from xeno.decorators import named

# --------------------------------------------------------------------
class Engine:
    TARGET_ATTR = "xeno.build.target"
    DEFAULT_ATTR = "xeno.build.default"

    def __init__(self):
        self.injector = AsyncInjector()

    def targets(self) -> list[str]:
        return [
            k
            for k, _ in self.injector.scan_resources(
                lambda _, v: v.check(self.TARGET_ATTR)
            )
        ]

    def default_target(self) -> Optional[str]:
        results = [
            k
            for k, _ in self.injector.scan_resources(
                lambda _, v: v.check(self.DEFAULT_ATTR)
            )
        ]
        assert len(results) <= 1, "More than one default target specified."
        return results[0] if results else None

    def provide(self, *args, **kwargs):
        self.injector.provide(*args, **{**kwargs, "is_singleton": True})

    def target(
        self,
        name: Optional[str] = None,
        *,
        factory=False,
        multi=False,
        default=False,
        sync=False,
        memoize=False
    ):
        """
        Decorator for defining a target recipe for a build.

        If `factory` or `multi` are true, the function is a recipe factory
        that returns one or more recipes and the values passed to it
        are the recipe objects named.

        If `name` is provided, it is used as the name of the recipe.  Otherwise,
        the name of the recipe is inferred to be the name of the decorated
        function.

        Otherwise, the function is interpreted as a recipe implementation
        method and the values passed to it when it is eventually called
        are the result values of its dependencies.

        If `default` is True, the target will be the default target
        when no target is specified at build time.  This method will
        throw ValueError if another target has already been specified
        as the default target.
        """

        def wrapper(f):
            @MethodAttributes.wraps(f)
            async def target_wrapper(*args, **kwargs):
                if factory or multi:
                    if multi:
                        return Recipe(f(*args, **kwargs), sync=sync, memoize=memoize)
                    else:
                        result = cast(Recipe, f(*args, **kwargs))
                        result.sync = sync
                        result.memoize = memoize
                        return result

                return Lambda(
                    f,
                    kwargs,
                    pflags=Lambda.KWARGS & Lambda.RESULTS,
                    sync=sync,
                    memoize=memoize,
                )

            attrs = MethodAttributes.for_method(target_wrapper, True, True)
            assert attrs is not None
            attrs.put(self.TARGET_ATTR)
            if default:
                attrs.put(self.DEFAULT_ATTR)
            if name is not None:
                target_wrapper = named(name)(target_wrapper)
            self.provide(target_wrapper)
            return target_wrapper

        return wrapper

    def build(self):
        with
