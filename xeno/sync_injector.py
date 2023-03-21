# --------------------------------------------------------------------
# sync.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday May 7, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import inspect
from typing import Optional, cast

from .abstract import AbstractInjector
from .attributes import (NOTHING, ClassAttributes, MethodAttributes,
                         get_injection_params, get_injection_points)
from .decorators import Tags, named, singleton
from .errors import (ClassInjectionError, MethodInjectionError,
                     MissingDependencyError, MissingResourceError)
from .namespaces import Namespace
from .utils import resolve_alias


# --------------------------------------------------------------------
class SyncInjector(AbstractInjector):
    """
    SyncInjector is a specialization of AbstractInjector that does not support
    async providers and can be run inside another event loop.
    """

    def create(self, class_):
        """
        Overrides: AbstractInjector
        """
        try:
            param_map, alias_map = self._resolve_dependencies(
                class_.__init__, unbound_ctor=True
            )
            attrs = MethodAttributes.for_method(class_.__init__)
            param_map = self._invoke_injection_interceptors(attrs, param_map, alias_map)
        except MethodInjectionError as e:
            raise ClassInjectionError(class_, e.name)

        instance = class_(**param_map)
        self._inject_instance(instance)
        return instance

    def inject(self, obj, aliases={}, namespace: Optional[str] = None):
        """
        Overrides: AbstractInjector
        """
        if inspect.isfunction(obj) or inspect.ismethod(obj):
            return self._inject_method(obj, aliases, namespace or "")
        return self._inject_instance(obj, aliases, namespace or "")

    def require(self, name, method=None):
        """
        Overrides: AbstractInjector
        """
        return self._require(name, method)

    def provide(self, name_or_method, value=NOTHING, is_singleton=False, namespace=None):
        """
        Overrides: AbstractInjector
        """

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
            self._bind_resource(value, namespace=namespace)
        else:
            @named(name)
            def wrapper():
                return value

            if is_singleton:
                wrapper = singleton(wrapper)
            self._bind_resource(wrapper, namespace=namespace)

    def _bind_resource(self, bound_method, module_aliases={}, namespace=None):
        """
        Overrides: AbstractInjector
        """

        params, _ = get_injection_params(bound_method)
        attrs = MethodAttributes.for_method(bound_method)
        assert attrs is not None

        using_namespaces = []
        name = cast(str, attrs.get(Tags.NAME))
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

        injected_method = self.inject(bound_method, aliases, namespace)

        if attrs.check(Tags.SINGLETON):
            def wrapper():
                if name not in self.singletons:
                    singleton = injected_method()
                    self.singletons[name] = singleton
                    return singleton
                return self.singletons[name]

            resource = wrapper
        else:
            resource = injected_method

        # Make the canonical full resource name available via 'resource-name'.
        attrs.put(Tags.RESOURCE_FULL_NAME, name)

        self.ns_index.add(name)
        self.resources[name] = resource
        self.resource_attrs[name] = attrs
        self.dep_graph[name] = lambda: [
            resolve_alias(x, aliases) for x in params
        ]

    def _resolve_dependencies(self, f, unbound_ctor=False, aliases={}, namespace=""):
        params, default_set = get_injection_params(f, unbound_ctor=unbound_ctor)
        attrs = MethodAttributes.for_method(f)
        assert attrs is not None
        param_map = {}
        param_resource_map = {}
        full_name = attrs.get(Tags.NAME)
        if namespace:
            full_name = Namespace.join(namespace, full_name)
            aliases = {**aliases, **self._get_aliases(attrs, [namespace])}

        try:
            resource_map = {}
            for param in params:
                if param in default_set and not self.has(param):
                    continue
                resource_name = param
                if resource_name.startswith(Namespace.SEP):
                    resource_name = resource_name[len(Namespace.SEP):]
                resource_name = resolve_alias(resource_name, aliases)
                resource_map[param] = self._require(resource_name)
                param_resource_map[param] = resource_name

            for k, c in resource_map.items():
                param_map[k] = c

        except MissingResourceError as e:
            raise MissingDependencyError(full_name, e.name) from e
        return param_map, param_resource_map

    def _require(self, name, method=None):
        if name not in self.resources:
            if method is not None:
                raise MethodInjectionError(method, name, "Resource was not provided.")
            raise MissingResourceError(name)
        if name in self.singletons:
            return self.singletons[name]
        return self.resources[name]()

    def _inject_instance(self, instance, aliases={}, namespace=""):
        class_attributes = ClassAttributes.for_class(instance.__class__)
        assert class_attributes is not None
        aliases = {**aliases, **class_attributes.get(Tags.ALIASES, {})}
        for _, injection_point in get_injection_points(instance):
            injected_method = self.inject(injection_point, aliases, namespace)
            injected_method()
        return instance

    def _inject_method(self, method, aliases_in={}, namespace=""):
        def wrapper():
            aliases = {**aliases_in}
            attrs = MethodAttributes.for_method(method)
            assert attrs is not None
            aliases = {**aliases, **attrs.get(Tags.ALIASES, {})}
            param_map, alias_map = self._resolve_dependencies(
                method, aliases=aliases, namespace=namespace
            )
            param_map = self._invoke_injection_interceptors(
                attrs, param_map, alias_map
            )
            return method(**param_map)
        return wrapper
