# --------------------------------------------------------------------
# async_injector.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday May 7, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import inspect
from collections import defaultdict
from typing import Optional, cast

from .abstract import AbstractInjector
from .attributes import (
    NOTHING,
    ClassAttributes,
    MethodAttributes,
    get_injection_params,
    get_injection_points,
)
from .decorators import Tags, named, singleton
from .errors import (
    ClassInjectionError,
    MethodInjectionError,
    MissingDependencyError,
    MissingResourceError,
)
from .namespaces import Namespace
from .utils import async_map, async_wrap, resolve_alias


# --------------------------------------------------------------------
class AsyncInjector(AbstractInjector):
    """
    A specialization of AbstractInjector, and the classic Injector
    which supports async providers and uses an asyncio event loop
    during dependency resolution.

    Use of this injector is preferred for flexibility if you know
    that it will not be run within an asyncio event loop.

    This form of Injector cannot be used within other event loops.
    If you wish to perform synchronous dependency injection inside
    of an asyncio event loop, use SyncInjector instead.
    """

    def __init__(self, *modules):
        """
        Create an Injector object.

        *modules: A list of modules to include in the injector.
                  More modules can be added later by calling
                  Injector.add_module().
        """
        self.async_injection_interceptors = []
        self.singleton_locks = defaultdict(asyncio.Lock)
        super().__init__(*modules)

    def add_async_injection_interceptor(self, interceptor):
        self.async_injection_interceptors.append(interceptor)

    def create(self, class_):
        """
        Overrides: AbstractInjector

        This method creates a new event loop.  If running from an existing
        event loop, await `create_async` instead.

        Create an instance of the specified class.  The class' constructor
        must follow the rules for @inject methods, such that all of its
        parameters refer to injectable resources or are optional.

        If the object needs to be constructed with objects not from the
        Injector, do not use this method.  Instead, instantiate the object
        with these parameters in the constructor, then mark one or more
        methods with @inject and pass the instance to Injector.inject().
        """
        return asyncio.run(self.create_async(class_))

    async def create_async(self, class_):
        """
        Create an instance of the specified class.  The class' constructor
        must follow the rules for @inject methods, such that all of its
        parameters refer to injectable resources or are optional.

        If the object needs to be constructed with objects not from the
        Injector, do not use this method.  Instead, instantiate the object
        with these parameters in the constructor, then mark one or more
        methods with @inject and pass the instance to Injector.inject().
        """
        try:
            param_map, alias_map = await self._resolve_dependencies(
                class_.__init__, unbound_ctor=True
            )
            attrs = MethodAttributes.for_method(class_.__init__)
            param_map = await self._async_invoke_injection_interceptors(
                attrs, param_map, alias_map
            )
        except MethodInjectionError as e:
            raise ClassInjectionError(class_, e.name)

        instance = class_(**param_map)
        await self._inject_instance(instance)
        return instance

    def inject(self, obj, aliases={}, namespace=""):
        """
        Overrides: AbstractInjector

        This method creates a new event loop.  If running from an existing
        event loop, await `inject_async` instead.

        Inject a method or object instance with resources from this Injector.

        obj: A method or object instance.  If this is a method, all named
             parameters are injected from the Injector.  If this is an
             instance, its methods are scanned for injection points and these
             methods are all invoked with resources from the Injector.
        aliases: An optional map from dependency alias to real dependency name.
        """
        return asyncio.run(self.inject_async(obj, aliases, namespace))

    async def inject_async(self, obj, aliases={}, namespace: Optional[str] = None):
        """
        Inject a method or object instance with resources from this Injector.

        obj: A method or object instance.  If this is a method, all named
             parameters are injected from the Injector.  If this is an
             instance, its methods are scanned for injection points and these
             methods are all invoked with resources from the Injector.
        aliases: An optional map from dependency alias to real dependency name.
        """
        if inspect.isfunction(obj) or inspect.ismethod(obj):
            return await self._inject_method(obj, aliases, namespace or "")
        return await self._inject_instance(obj, aliases, namespace or "")

    def require(self, name, method=None):
        """
        Overrides: AbstractInjector

        This method creates a new event loop.  If running from an existing
        event loop, await `require_async` instead.

        Require a named resource from this Injector.  If it can't be provided,
        an InjectionError is raised.

        Optionally, a method can be specified.  This indicates the method that
        requires the resource for injection, and causes this method to throw
        MethodInjectionError instead of InjectionError if the resource was
        not provided.
        """
        return asyncio.run(self.require_async(name, method))

    async def require_async(self, name, method=None):
        """
        Require a named resource from this Injector.  If it can't be provided,
        an InjectionError is raised.

        Optionally, a method can be specified.  This indicates the method that
        requires the resource for injection, and causes this method to throw
        MethodInjectionError instead of InjectionError if the resource was
        not provided.
        """
        return await self._require_coro(name, method)

    def provide(
        self, name_or_method, value=NOTHING, is_singleton=False, namespace=None
    ):
        """
        Overrides: AbstractInjector

        This method creates a new event loop.  If running from an existing
        event loop, await `provide_async` instead.
        """

        return asyncio.run(
            self.provide_async(name_or_method, value, is_singleton, namespace)
        )

    async def provide_async(
        self, name_or_method, value=NOTHING, is_singleton=False, namespace=None
    ):

        if inspect.ismethod(name_or_method) or inspect.isfunction(name_or_method):
            value = name_or_method
            attrs = MethodAttributes.for_method(name_or_method)
            assert attrs is not None
            name = attrs.get(Tags.NAME)
        elif value is NOTHING:
            raise ValueError("A name and value or just a method must be provided.")
        else:
            name = name_or_method

        if name in self.singletons:
            del self.singletons[name]
        if inspect.ismethod(value) or inspect.isfunction(value):
            if is_singleton:
                value = singleton(value)
            await self._bind_resource_async(value, namespace=namespace)
        else:

            @named(name)
            def wrapper():
                return value

            if is_singleton:
                wrapper = singleton(wrapper)
            await self._bind_resource_async(wrapper, namespace=namespace)

    async def _bind_resource_async(
        self, bound_method, module_aliases={}, namespace=None
    ):
        params, _ = get_injection_params(bound_method)
        attrs = MethodAttributes.for_method(bound_method)
        assert attrs is not None

        using_namespaces = []
        name = cast(str, attrs.get(Tags.NAME))
        assert name is not None
        # Allow names that begin with the namespace separator
        # to be scoped outside of the specified namespace.
        if name.startswith(Namespace.SEP):
            name = name[len(Namespace.SEP):]
        elif namespace is not None:
            name = Namespace.join(namespace, name)
            using_namespaces.append(namespace)

        aliases = {
            **(self._get_aliases(attrs, using_namespaces) or {}),
            **module_aliases,
        }

        injected_method = await self.inject_async(bound_method, aliases, namespace)

        if attrs.check(Tags.SINGLETON):
            async def wrapper():
                async with self.singleton_locks[name]:
                    if name not in self.singletons:
                        singleton = await injected_method()
                        self.singletons[name] = singleton
                        return singleton
                    return self.singletons[name]

            resource = wrapper
        else:
            resource = injected_method

        attrs.put(Tags.RESOURCE_FULL_NAME, name)

        self.ns_index.add(name)
        self.resources[name] = resource
        self.resource_attrs[name] = attrs
        self.dep_graph[name] = lambda: [
            resolve_alias(x, aliases) for x in params
        ]

    def _bind_resource(self, bound_method, module_aliases={}, namespace=None):
        """
        Overrides: AbstractInjector
        """
        return asyncio.run(
            self._bind_resource_async(bound_method, module_aliases, namespace)
        )

    async def _resolve_dependencies(
        self, f, unbound_ctor=False, aliases={}, namespace=""
    ):
        params, default_set = get_injection_params(f, unbound_ctor=unbound_ctor)
        attrs = MethodAttributes.for_method(f)
        assert attrs is not None
        param_map: dict = {}
        param_resource_map = {}
        full_name = attrs.get(Tags.NAME)
        if namespace:
            full_name = Namespace.join(namespace, full_name)
            aliases = {**aliases, **self._get_aliases(attrs, [namespace])}

        try:
            resource_async_map = {}
            for param in params:
                if param in default_set and not self.has(param):
                    continue
                resource_name = param
                if resource_name.startswith(Namespace.SEP):
                    resource_name = resource_name[len(Namespace.SEP):]
                resource_name = resolve_alias(resource_name, aliases)
                resource_async_map[param] = self._require_coro(resource_name)
                param_resource_map[param] = resource_name

            param_map = dict(
                await asyncio.gather(
                    *(async_map(k, c) for k, c in resource_async_map.items())
                )
            )

        except MissingResourceError as e:
            raise MissingDependencyError(full_name, e.name) from e
        return param_map, param_resource_map

    async def _inject_instance(self, instance, aliases={}, namespace=""):
        class_attributes = ClassAttributes.for_class(instance.__class__)
        assert class_attributes is not None
        aliases = {**aliases, **class_attributes.get(Tags.ALIASES, {})}
        for _, injection_point in get_injection_points(instance):
            injected_method = await self.inject_async(
                injection_point, aliases, namespace
            )
            await injected_method()
        return instance

    async def _inject_method(self, method, aliases_in={}, namespace=""):
        async def wrapper():
            aliases = {**aliases_in}
            attrs = MethodAttributes.for_method(method)
            assert attrs is not None
            aliases = {**aliases, **attrs.get(Tags.ALIASES, {})}
            param_map, alias_map = await self._resolve_dependencies(
                method, aliases=aliases, namespace=namespace
            )
            param_map = await self._async_invoke_injection_interceptors(
                attrs, param_map, alias_map
            )
            return await async_wrap(method, **param_map)

        return wrapper

    async def _async_invoke_injection_interceptors(self, attrs, param_map, alias_map):
        param_map = self._invoke_injection_interceptors(attrs, param_map, alias_map)
        for interceptor in self.async_injection_interceptors:
            param_map = await interceptor(attrs, param_map, alias_map)
        return param_map

    async def _require_coro(self, name, method=None):
        """
        For internal use only.  Used to tie together resources needed
        by other resources in this injector.
        """
        if name not in self.resources:
            if method is not None:
                raise MethodInjectionError(method, name, "Resource was not provided.")
            raise MissingResourceError(name)
        if name in self.singletons:
            return self.singletons[name]
        return await async_wrap(self.resources[name])
